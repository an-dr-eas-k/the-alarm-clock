import datetime
import logging
from timeit import timeit
from core.application.controls import safe_action
from core.domain.events import (
    ForcedDisplayUpdateEvent,
    PlaybackChangedEvent,
    SpotifyStoppedEvent,
    SunEventOccurredEvent,
    VolumeChangedEvent,
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

logger = logging.getLogger("tac.core.application.system_service")


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
        self.event_bus.on(SpotifyStoppedEvent)(self.handle_spotify_stopped)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)

        self._update_weather_status()
        self._add_scheduler_jobs()
        self.scheduler_service.log_active_jobs(SchedulerStores.default.value)

    def _add_scheduler_jobs(self):
        self.scheduler_service.add_job(
            self._emit_regular_display_update,
            trigger="interval",
            start_date=datetime.datetime.today(),
            seconds=self.alarm_clock_context.config.refresh_timeout_in_secs,
            id=SchedulerJobIds.regular_display_refresh.value,
            jobstore=SchedulerStores.default.value,
        )

        self.scheduler_service.add_job(
            self._update_wifi_status,
            trigger="interval",
            seconds=60,
            id=SchedulerJobIds.wifi_check.value,
            jobstore=SchedulerStores.default.value,
        )

        self.scheduler_service.add_job(
            self._update_weather_status,
            trigger="interval",
            minutes=5,
            id=SchedulerJobIds.weather_update_interval.value,
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

    def handle_spotify_stopped(self, _: SpotifyStoppedEvent):
        restart_spotify_daemon()

    def _volume_changed(self, _: VolumeChangedEvent):
        self.start_hide_volume_meter_trigger()

    def start_hide_volume_meter_trigger(self):
        self.scheduler_service.start_generic_trigger(
            SchedulerJobIds.hide_volume_meter.value,
            datetime.timedelta(seconds=5),
            func=self.display_content.hide_volume_meter,
        )

    def handle_playback_changed(self, event: PlaybackChangedEvent):
        if event.playback_mode == Mode.Idle:
            self.scheduler_service.stop_generic_trigger(
                SchedulerJobIds.hide_volume_meter.value
            )

    def handle_alarm_stopped(self, _: AlarmStoppedEvent):
        self.scheduler_service.stop_generic_trigger(
            SchedulerJobIds.ensure_stable_wifi.value
        )

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

        safe_action(do, "updating weather status", logger=logger)

    def _update_wifi_status(self):
        def do():
            is_online = is_internet_available()

            if is_online == self.alarm_clock_context.environment.is_online:
                return

            logger.info("change wifi state, is online: %s", is_online)
            self.event_bus.emit(WifiStatusChangedEvent(is_online))
            self.alarm_clock_context.environment.is_online = is_online

        safe_action(do, "updating wifi status", logger=logger)

    def _sun_event_occured(self, event: SunEvent):
        def do():
            self.event_bus.emit(SunEventOccurredEvent(event))
            self.alarm_clock_context.environment.is_daytime = event == SunEvent.sunrise
            self.init_sun_event_scheduler(event)

        safe_action(do, "sun event %s" % event, logger=logger)

    def _emit_regular_display_update(self):
        def do():
            start_time = GeoLocation().now()
            current_second = start_time.second
            new_blink_state = self.display_content.show_blink_segment

            if self._previous_second != current_second:
                new_blink_state = not self.display_content.show_blink_segment
                self._previous_second = current_second

            if self.display_content.update_presentation_state(
                show_blink_segment=new_blink_state,
                room_brightness=RoomBrightness(self.get_room_brightness()),
            ):
                self.event_bus.emit(
                    ForcedDisplayUpdateEvent(
                        suppress_logging=True,
                    )
                )
                # self.display_content.refresh_duration_in_ms = int(
                #     (GeoLocation().now() - start_time).total_seconds() * 1000
                # )

        safe_action(do, debug_msg="regular display update", logger=logger)

    def get_room_brightness(self):
        start_time = GeoLocation().now()

        rb = self.brightness_sensor.get_room_brightness()

        self.display_content.refresh_duration_in_ms = int(
            (GeoLocation().now() - start_time).total_seconds() * 1000
        )
        return rb
