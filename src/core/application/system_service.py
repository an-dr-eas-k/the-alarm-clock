import datetime
import logging
import traceback
from core.domain.events import (
    ForcedDisplayUpdateEvent,
    PlaybackChangedEvent,
    SunEventOccurredEvent,
    WifiStatusChangedEvent,
    AlarmTriggeredEvent,
    AlarmStoppedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    Mode,
    RoomBrightness,
    SchedulerJobIds,
)
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from core.infrastructure.scheduler import SchedulerService, SchedulerStores
from core.interface.display.display_content import DisplayContent
from utils.geolocation import GeoLocation, SunEvent
from utils.network import is_internet_available
from utils.os import restart_spotify_daemon

logger = logging.getLogger("tac.system_service")


class SystemService:
    _previous_second = GeoLocation().now().second

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        scheduler_service: SchedulerService,
        event_bus: EventBus,
        display_content: DisplayContent,
        brightness_sensor: IBrightnessSensor,
    ):
        self.alarm_clock_context = alarm_clock_context
        self.scheduler_service = scheduler_service
        self.event_bus = event_bus
        self.display_content = display_content
        self.brightness_sensor = brightness_sensor

        self.event_bus.on(WifiStatusChangedEvent)(self.handle_wifi_status_changed)
        self.event_bus.on(AlarmTriggeredEvent)(self.handle_alarm_triggered)
        self.event_bus.on(AlarmStoppedEvent)(self.handle_alarm_stopped)
        self.event_bus.on(PlaybackChangedEvent)(self.handle_playback_changed)

        self._update_weather_status()
        self._add_scheduler_jobs()
        self.scheduler_service.log_active_jobs(SchedulerStores.default.value)

    def _add_scheduler_jobs(self):
        self.scheduler_service.add_job(
            self._emit_regular_display_update,
            trigger="interval",
            start_date=datetime.datetime.today(),
            seconds=self.alarm_clock_context.config.refresh_timeout_in_secs,
            id="display_interval",
            jobstore=SchedulerStores.default.value,
        )

        self.scheduler_service.add_job(
            self._update_wifi_status,
            trigger="interval",
            seconds=60,
            id="wifi_check_interval",
            jobstore=SchedulerStores.default.value,
        )

        self.scheduler_service.add_job(
            self._update_weather_status,
            trigger="interval",
            minutes=5,
            id="weather_check_interval",
            jobstore=SchedulerStores.default.value,
        )

        for event in SunEvent.__members__.values():
            self.init_sun_event_scheduler(event)

    def init_sun_event_scheduler(self, event: SunEvent):
        self.scheduler_service.add_cron_job(
            lambda: self._sun_event_occured(event),
            id=event.value,
            jobstore=SchedulerStores.default.value,
            **self.alarm_clock_context.environment.geo_location.get_sun_event_cron_args(
                event
            ),
        )

    def handle_alarm_triggered(self, _: AlarmTriggeredEvent):
        # Increase wifi check frequency during alarm
        self.scheduler_service.add_job(
            self._update_wifi_status,
            trigger="interval",
            seconds=5,
            id=SchedulerJobIds.ensure_stable_wifi.value,
            jobstore=SchedulerStores.default.value,
        )

    def handle_playback_changed(self, event: PlaybackChangedEvent):
        if (
            True
            and event.playback_mode != Mode.Spotify
            and self.display_content.playback_content.playback_mode == Mode.Spotify
        ):
            restart_spotify_daemon()

        self.scheduler_service.stop_generic_trigger(
            SchedulerJobIds.hide_volume_meter.value
        )

    def handle_alarm_stopped(self, _: AlarmStoppedEvent):
        self.scheduler_service.stop_generic_trigger(SchedulerJobIds.ensure_stable_wifi)

    def handle_wifi_status_changed(self, event: WifiStatusChangedEvent):
        if event.is_online:
            self._update_weather_status()
        else:
            self.alarm_clock_context.environment.current_weather = None

    def _update_weather_status(self):
        def do():
            if not self.alarm_clock_context.environment.is_online:
                self.alarm_clock_context.environment.current_weather = None
                return

            new_weather = GeoLocation().get_current_weather()
            logger.info("weather updating: %s", new_weather)
            self.alarm_clock_context.environment.current_weather = new_weather

        self._action(do)

    def _update_wifi_status(self):
        def do():
            is_online = is_internet_available()

            if is_online == self.alarm_clock_context.environment.is_online:
                return

            logger.info("change wifi state, is online: %s", is_online)
            self.event_bus.emit(WifiStatusChangedEvent(is_online))
            self.alarm_clock_context.environment.is_online = is_online

        self._action(do)

    def _sun_event_occured(self, event: SunEvent):
        def do():
            self.event_bus.emit(SunEventOccurredEvent(event))
            self.alarm_clock_context.environment.is_daytime = event == SunEvent.sunrise
            self.init_sun_event_scheduler(event)

        self._action(do, "sun event %s" % event)

    def _emit_regular_display_update(self):
        def do():
            logger.debug("update display")
            current_second = GeoLocation().now().second
            new_blink_state = self.display_content.show_blink_segment

            if self._previous_second != current_second:
                new_blink_state = not self.display_content.show_blink_segment
                self._previous_second = current_second

            if self.display_content.update_presentation_state(
                show_blink_segment=new_blink_state,
                room_brightness=RoomBrightness(self.get_room_brightness()),
            ):
                self.event_bus.emit(ForcedDisplayUpdateEvent(suppress_logging=True))

        self._action(do)

    def get_room_brightness(self):
        return self.brightness_sensor.get_room_brightness()

    def _action(self, action, info: str = None):
        try:
            if info:
                logger.info(info)
            action()
        except:
            logger.error("%s", traceback.format_exc())
