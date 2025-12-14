import datetime
import logging
import threading
from core.application.controls import safe_action
from core.domain.events import (
    ForcedDisplayUpdateEvent,
    PlaybackChangedEvent,
    PreAlarmTriggeredEvent,
    ShutdownSystemRequest,
    SpotifyStoppedEvent,
    SunEventOccurredEvent,
    TerminateAppRequest,
    VolumeChangedEvent,
    WeatherUpdatedEvent,
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
from utils.os_interactions import OSInteraction

from utils.memory_profiler import print_memory_usage
from utils.thread_profiler import print_thread_usage

logger = logging.getLogger("tac.core.application.system_service")


class SystemService:
    _previous_tac_time = GeoLocation().now()

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        scheduler_service: SchedulerService,
        event_bus: EventBus,
        display_content: DisplayContent,
        brightness_sensor: IBrightnessSensor,
        os_interaction: OSInteraction,
    ):
        self.alarm_clock_context = alarm_clock_context
        self.scheduler_service = scheduler_service
        self.event_bus = event_bus
        self.display_content = display_content
        self.brightness_sensor = brightness_sensor
        self.os_interaction = os_interaction

        self.event_bus.on(WifiStatusChangedEvent)(self.handle_wifi_status_changed)
        self.event_bus.on(AlarmTriggeredEvent)(self.handle_alarm_triggered)
        self.event_bus.on(AlarmStoppedEvent)(self.handle_alarm_stopped)
        self.event_bus.on(SpotifyStoppedEvent)(self.handle_spotify_stopped)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)
        self.event_bus.on(ForcedDisplayUpdateEvent)(self.handle_forced_display_update)
        self.event_bus.on(TerminateAppRequest)(self.handle_terminate_request)
        self.event_bus.on(ShutdownSystemRequest)(self.handle_shutdown_system_request)
        self.event_bus.on(PreAlarmTriggeredEvent)(self.handle_pre_alarm_triggered)

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

        self.scheduler_service.add_job(
            print_memory_usage,
            trigger="cron",
            hour="*",
            id=SchedulerJobIds.memory_usage_logger.value,
            jobstore=SchedulerStores.default.value,
        )

        self.scheduler_service.add_job(
            print_thread_usage,
            trigger="cron",
            hour="*",
            minute="5-59/10",
            id=SchedulerJobIds.thread_usage_logger.value,
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
        self.os_interaction.restart_spotify_daemon()

    def _volume_changed(self, _: VolumeChangedEvent):
        self.start_hide_volume_meter_trigger()

    def start_hide_volume_meter_trigger(self):
        self.scheduler_service.start_generic_trigger(
            SchedulerJobIds.hide_volume_meter.value,
            datetime.timedelta(seconds=5),
            func=self.display_content.hide_volume_meter,
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

    def handle_forced_display_update(self, _: ForcedDisplayUpdateEvent):
        self._previous_tac_time = GeoLocation().now()

    def handle_pre_alarm_triggered(self, _: PreAlarmTriggeredEvent):
        if not self.alarm_clock_context.environment.is_online:
            self.os_interaction.restart_networking_service()

    def handle_shutdown_system_request(self, event: ShutdownSystemRequest):
        def do():
            if event.reboot:
                self.os_interaction.reboot_system()
            else:
                self.os_interaction.shutdown_system()

        safe_action(do, "shutting down system", logger=logger)

    def handle_terminate_request(self, _: TerminateAppRequest):
        def do():
            for thread in threading.enumerate():
                logger.info("Thread: %s", thread)
            self.event_bus.emit(PlaybackChangedEvent(playback_mode=Mode.Idle))
            # self.scheduler_service.shutdown()
            self.event_bus.clear()

            logger.info("application shutdown completed.")

        safe_action(do, "terminating application", logger=logger)

    def _update_weather_status(self):
        def do():
            if not self.alarm_clock_context.environment.is_online:
                self.alarm_clock_context.environment.current_weather = None
                return

            new_weather = GeoLocation().get_current_weather()
            logger.info("weather updating: %s", new_weather)
            self.alarm_clock_context.environment.current_weather = new_weather
            self.event_bus.emit(WeatherUpdatedEvent())

        safe_action(do, "updating weather status", logger=logger)

    def _update_wifi_status(self):
        def do():
            is_online = self.os_interaction.is_internet_available()

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
            tac_time = GeoLocation().now()
            new_blink_state = self.display_content.show_blink_segment

            if self._previous_tac_time.second != tac_time.second:
                new_blink_state = not self.display_content.show_blink_segment
                self._previous_tac_time = tac_time

            if self.display_content.update_presentation_state(
                show_blink_segment=new_blink_state,
                room_brightness=RoomBrightness(self.get_room_brightness()),
            ):
                self.event_bus.emit(
                    ForcedDisplayUpdateEvent(
                        suppress_logging=True,
                    )
                )
                self.display_content.refresh_duration_in_ms = int(
                    (GeoLocation().now() - tac_time).total_seconds() * 1000
                )

        safe_action(do, debug_msg="regular display update", logger=logger)

    def get_room_brightness(self):
        return self.brightness_sensor.get_room_brightness()
