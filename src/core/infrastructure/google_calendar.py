import json
import logging
import urllib.parse
from datetime import datetime
from typing import List

from tornado.httpclient import HTTPClient, HTTPError, HTTPRequest

from core.domain.calendar_model import CalendarEvent

logger = logging.getLogger("tac.core.infrastructure.google_calendar")

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleCalendarClient:
    """Infrastructure: reads events from a user's primary Google Calendar via REST."""

    def fetch_events(
        self,
        access_token: str,
        account_email: str,
        time_min: datetime,
        time_max: datetime,
    ) -> List[CalendarEvent]:
        params = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "50",
        }
        url = f"{EVENTS_URL}?{urllib.parse.urlencode(params)}"
        client = HTTPClient()
        try:
            request = HTTPRequest(
                url,
                method="GET",
                headers={"Authorization": f"Bearer {access_token}"},
                request_timeout=15,
            )
            response = client.fetch(request)
            payload = json.loads(response.body)
        except HTTPError:
            logger.warning(
                "failed fetching calendar events for %s", account_email, exc_info=True
            )
            return []
        finally:
            client.close()

        events = []
        for item in payload.get("items", []):
            if item.get("status") == "cancelled":
                continue
            start_info = item.get("start", {})
            end_info = item.get("end", {})
            is_all_day = "date" in start_info
            start = self._parse_datetime(start_info)
            end = self._parse_datetime(end_info)
            if start is None:
                continue
            events.append(
                CalendarEvent(
                    event_id=item.get("id"),
                    account_email=account_email,
                    summary=item.get("summary") or "(no title)",
                    start=start,
                    end=end,
                    is_all_day=is_all_day,
                    response_status=self._response_status(item, account_email),
                    html_link=item.get("htmlLink"),
                )
            )
        return events

    def _parse_datetime(self, info: dict):
        if "dateTime" in info:
            value = info["dateTime"]
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        if "date" in info:
            return datetime.fromisoformat(info["date"] + "T00:00:00+00:00")
        return None

    def _response_status(self, item: dict, account_email: str) -> str:
        attendees = item.get("attendees") or []
        if not attendees:
            # events without attendees (self-created, or organizer-only) count as accepted
            return "accepted"
        for attendee in attendees:
            if attendee.get("self") or attendee.get("email") == account_email:
                return attendee.get("responseStatus", "needsAction")
        return "accepted"
