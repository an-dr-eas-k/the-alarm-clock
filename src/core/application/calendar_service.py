from __future__ import annotations

import datetime
import logging
import time
from typing import Dict, List, Optional

from core.domain.calendar_model import CalendarEvent
from core.domain.events import (
    CalendarEventReminderEvent,
    CalendarEventsUpdatedEvent,
    ConfigChangedEvent,
    PlaybackChangedEvent,
)
from core.domain.model import AlarmClockContext, Mode
from core.infrastructure.event_bus import EventBus
from core.infrastructure.google_auth import (
    AccessDenied,
    AuthorizationExpired,
    AuthorizationPending,
    GoogleAuthError,
    GoogleDeviceAuthClient,
    SlowDown,
)
from core.infrastructure.google_calendar import GoogleCalendarClient
from core.infrastructure.google_token_store import GoogleTokenStore
from core.infrastructure.scheduler import SchedulerService, SchedulerStores
from core.interface.display.display_content import DisplayContent
from utils.geolocation import GeoLocation

logger = logging.getLogger("tac.core.application.calendar_service")

CALENDAR_POLL_JOB_ID = "calendar_poll_trigger"
CALENDAR_REMINDER_STOP_JOB_ID = "calendar_reminder_stop_trigger"
CALENDAR_REMINDER_JOB_PREFIX = "calendar_reminder_"


class CalendarService:
    """Application Service: orchestrates linking Google accounts (login via the
    OAuth device flow) and reading/announcing their calendar events.

    All Google/HTTP specifics are delegated to infrastructure collaborators;
    this service only coordinates domain objects, the scheduler and the event
    bus, in line with the Dependency Rule.
    """

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        display_content: DisplayContent,
        event_bus: EventBus,
        scheduler_service: SchedulerService,
        token_store: GoogleTokenStore,
        auth_client: Optional[GoogleDeviceAuthClient],
        calendar_client: GoogleCalendarClient,
    ):
        self.alarm_clock_context = alarm_clock_context
        self.display_content = display_content
        self.event_bus = event_bus
        self.scheduler_service = scheduler_service
        self.token_store = token_store
        self.auth_client = auth_client
        self.calendar_client = calendar_client
        self._pending_logins: Dict[str, dict] = {}

        self.event_bus.on(ConfigChangedEvent)(self._config_changed)
        self.event_bus.on(CalendarEventReminderEvent)(self._play_reminder)

        self._schedule_polling()
        self.refresh_events()

    @property
    def config(self):
        return self.alarm_clock_context.config

    def is_configured(self) -> bool:
        """Whether a Google OAuth client (client_id/secret) has been provided."""
        return self.auth_client is not None

    # ---------------- Login (device flow) ----------------

    def start_device_login(self) -> dict:
        if not self.is_configured():
            raise GoogleAuthError(
                "Google OAuth client is not configured (missing google_oauth_secret.json)"
            )
        result = self.auth_client.request_device_code()
        device_code = result["device_code"]
        self._pending_logins[device_code] = {
            "created_at": time.time(),
            "expires_in": result.get("expires_in", 1800),
        }
        return {
            "device_code": device_code,
            "user_code": result["user_code"],
            "verification_url": result.get(
                "verification_url", result.get("verification_uri")
            ),
            "interval": result.get("interval", 5),
            "expires_in": result.get("expires_in", 1800),
        }

    def poll_device_login(self, device_code: str) -> dict:
        if not self.is_configured():
            return {"status": "error", "message": "google login is not configured"}

        pending = self._pending_logins.get(device_code)
        if pending and time.time() - pending["created_at"] > pending["expires_in"]:
            self._pending_logins.pop(device_code, None)
            return {"status": "expired"}

        try:
            token_result = self.auth_client.poll_for_token(device_code)
        except AuthorizationPending:
            return {"status": "pending"}
        except SlowDown:
            return {"status": "pending"}
        except AuthorizationExpired:
            self._pending_logins.pop(device_code, None)
            return {"status": "expired"}
        except AccessDenied:
            self._pending_logins.pop(device_code, None)
            return {"status": "denied"}
        except GoogleAuthError as e:
            logger.warning("google auth error while polling: %s", e)
            return {"status": "error", "message": str(e)}

        self._pending_logins.pop(device_code, None)

        access_token = token_result["access_token"]
        userinfo = self.auth_client.get_userinfo(access_token)
        email = userinfo.get("email")
        picture = userinfo.get("picture")

        if not email or email not in (self.config.allowed_google_emails or []):
            logger.warning("google login rejected for non-allowed user: %s", email)
            self.auth_client.revoke(access_token)
            return {"status": "not_allowed", "email": email}

        self.token_store.save_tokens(
            email=email,
            access_token=access_token,
            refresh_token=token_result.get("refresh_token"),
            expires_in=token_result.get("expires_in", 3600),
        )
        logger.info("linked google account for calendar reading: %s", email)
        self.refresh_events()
        return {"status": "complete", "email": email, "picture": picture}

    def logout(self, email: str):
        self.token_store.remove(email)
        self.refresh_events()

    def is_account_linked(self, email: str) -> bool:
        return self.token_store.get(email) is not None

    # ---------------- Calendar polling ----------------

    def _config_changed(self, _: ConfigChangedEvent):
        self._schedule_polling()

    def _schedule_polling(self):
        self.scheduler_service.add_job(
            self.refresh_events,
            trigger="interval",
            minutes=max(1, self.config.calendar_poll_interval_mins),
            job_id=CALENDAR_POLL_JOB_ID,
            jobstore=SchedulerStores.default.value,
            replace_existing=True,
        )

    def get_upcoming_events(self) -> List[CalendarEvent]:
        """Events starting within `calendar_display_window_hours` (for display/UI)."""
        return self.display_content.upcoming_calendar_events(
            self.config.calendar_display_window_hours
        )

    def refresh_events(self):
        if not self.is_configured():
            return

        emails = self.token_store.all_emails()
        if not emails:
            self.display_content.update_calendar_events([])
            return

        now = GeoLocation().now()
        horizon = datetime.timedelta(hours=self.config.calendar_fetch_horizon_hours)
        all_events: List[CalendarEvent] = []
        for email in emails:
            try:
                access_token = self._get_valid_access_token(email)
                if access_token is None:
                    continue
                events = self.calendar_client.fetch_events(
                    access_token=access_token,
                    account_email=email,
                    time_min=now,
                    time_max=now + horizon,
                )
                all_events.extend(events)
            except Exception:
                logger.warning(
                    "failed to refresh calendar events for %s", email, exc_info=True
                )

        all_events.sort(key=lambda e: e.start)
        self.display_content.update_calendar_events(all_events)
        self.event_bus.emit(CalendarEventsUpdatedEvent(events=all_events))
        self._schedule_reminders(all_events)

    def _get_valid_access_token(self, email: str) -> Optional[str]:
        entry = self.token_store.get(email)
        if entry is None:
            return None
        if not self.token_store.is_access_token_expired(email):
            return entry["access_token"]

        refresh_token = entry.get("refresh_token")
        if not refresh_token:
            logger.warning("no refresh token stored for %s, re-login required", email)
            return None
        try:
            result = self.auth_client.refresh_access_token(refresh_token)
            self.token_store.save_tokens(
                email=email,
                access_token=result["access_token"],
                refresh_token=refresh_token,
                expires_in=result.get("expires_in", 3600),
            )
            return result["access_token"]
        except Exception:
            logger.warning(
                "failed to refresh google token for %s", email, exc_info=True
            )
            return None

    def _schedule_reminders(self, events: List[CalendarEvent]):
        now = GeoLocation().now()
        lead = datetime.timedelta(seconds=self.config.calendar_reminder_lead_seconds)
        active_job_ids = set()

        for event in events:
            if not event.is_accepted() or event.is_all_day:
                continue
            reminder_time = event.start - lead
            if reminder_time <= now:
                continue
            job_id = f"{CALENDAR_REMINDER_JOB_PREFIX}{event.event_id}"
            active_job_ids.add(job_id)
            self.scheduler_service.add_or_replace_date_job(
                func=self._trigger_reminder,
                args=[event],
                run_date=reminder_time,
                job_id=job_id,
                jobstore=SchedulerStores.default.value,
            )

        for job in self.scheduler_service.get_jobs(
            jobstore=SchedulerStores.default.value
        ):
            if (
                job.id.startswith(CALENDAR_REMINDER_JOB_PREFIX)
                and job.id not in active_job_ids
            ):
                self.scheduler_service.remove_job(
                    job.id, jobstore=SchedulerStores.default.value
                )

    def _trigger_reminder(self, event: CalendarEvent):
        self.event_bus.emit(CalendarEventReminderEvent(calendar_event=event))

    def _play_reminder(self, event: CalendarEventReminderEvent):
        reminder_stream = self.config.get_calendar_reminder_stream()
        logger.info(
            "playing calendar reminder sound for '%s'", event.calendar_event.summary
        )
        self.event_bus.emit(
            PlaybackChangedEvent(
                Mode.Music,
                reminder_stream,
                absolute_volume=self.config.default_volume,
            )
        )
        self.scheduler_service.start_generic_trigger(
            CALENDAR_REMINDER_STOP_JOB_ID,
            datetime.timedelta(seconds=self.config.calendar_reminder_duration_secs),
            func=self._stop_reminder,
        )

    def _stop_reminder(self):
        self.event_bus.emit(PlaybackChangedEvent(Mode.Idle))
