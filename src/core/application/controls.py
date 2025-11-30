import datetime
from enum import Enum
import logging
import os
import traceback
from apscheduler.job import Job
from core.domain.events import (
    AudioStreamChangeRequest,
    AudioStreamChangedEvent,
    ConfigChangedEvent,
    ForcedDisplayUpdateEvent,
    SpeakerErrorEvent,
    SpotifyStreamChangeRequest,
    ToggleAudioRequest,
    AlarmTriggeredEvent,
    AlarmStoppedEvent,
    SunEventOccurredEvent,
    VolumeChangeRequest,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    AudioStream,
    OfflineStream,
    PlaybackContent,
    Mode,
    RoomBrightness,
    SpotifyStream,
    StreamAudioEffect,
    Config,
)
from core.interface.display.display_content import DisplayContent
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from core.infrastructure.scheduler import SchedulerService, SchedulerStores
from utils.geolocation import GeoLocation, SunEvent
from utils.network import is_internet_available
from utils.os import restart_spotify_daemon
from resources.resources import active_alarm_definition_file

logger = logging.getLogger("tac.controls")


class SchedulerJobIds(Enum):
    hide_volume_meter = "hide_volume_meter_trigger"
    stop_alarm = "stop_alarm_trigger"
    ensure_stable_wifi = "ensure_stable_wifi_trigger"


class Controls:
    scheduler_service: SchedulerService
    alarm_clock_context: AlarmClockContext
    rotary_encoder_manager = None
    _previous_second = GeoLocation().now().second

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        brightness_sensor: IBrightnessSensor,
        event_bus: EventBus,
        scheduler_service: SchedulerService,
    ) -> None:
        self.alarm_clock_context = alarm_clock_context
        self.display_content = display_content
        self.playback_content = playback_content
        self.brightness_sensor = brightness_sensor
        self.event_bus = event_bus
        self.scheduler_service = scheduler_service
        self.event_bus.on(ToggleAudioRequest)(self._toggle_stream)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)
        self.event_bus.on(WifiStatusChangedEvent)(self._wifi_status_changed)
        self.event_bus.on(ConfigChangedEvent)(self._config_changed)
        self.event_bus.on(AlarmTriggeredEvent)(self._alarm_triggered)
        self.event_bus.on(AlarmStoppedEvent)(self._alarm_stopped_event)
        self.event_bus.on(SpeakerErrorEvent)(self._handle_speaker_error)
        self.event_bus.on(SpotifyStreamChangeRequest)(
            self._spotify_stream_change_request
        )

        self._update_weather_status()
        self._add_scheduler_jobs()
        self.scheduler_service.log_active_jobs(SchedulerStores.default.value)

    def consider_failed_alarm(self):
        if os.path.exists(active_alarm_definition_file):
            ad: AlarmDefinition = AlarmDefinition.deserialize(
                active_alarm_definition_file
            )
            ad.id = -1
            logger.info("failed audioeffect found %s", ad.alarm_name)
            self._ring_alarm(ad)

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

    def start_hide_volume_meter_trigger(self):
        self.scheduler_service.start_generic_trigger(
            SchedulerJobIds.hide_volume_meter.value,
            datetime.timedelta(seconds=5),
            func=self.display_content.hide_volume_meter,
        )

    def _config_changed(self, event: ConfigChangedEvent):
        config: Config = event.config
        self.scheduler_service.remove_all_jobs(jobstore=SchedulerStores.alarm.value)
        alDef: AlarmDefinition
        for alDef in config.alarm_definitions:
            if not alDef.is_active:
                continue
            logger.info("adding job for '%s'", alDef.alarm_name)
            self.scheduler_service.add_cron_job(
                func=self._ring_alarm,
                args=(alDef,),
                id=f"{alDef.id}",
                jobstore=SchedulerStores.alarm.value,
                **alDef.get_cron_args(),
            )
        self.scheduler_service.cleanup_alarms(config)
        self.display_content.update_next_alarm(
            self.scheduler_service.get_next_alarm_info()
        )

    def action(action, info: str = None):
        try:
            if info:
                logger.info(info)
            action()
        except:
            logger.error("%s", traceback.format_exc())

    def _toggle_stream(self, _: ToggleAudioRequest):
        if self.playback_content.playback_mode == Mode.Alarm:
            self._set_to_idle_mode(alarm_stopped_reason="manual")
            return

        if self.playback_content.playback_mode in [
            Mode.Music,
            Mode.Spotify,
        ]:
            self._set_to_idle_mode()
            return

        audio_stream = self.alarm_clock_context.config.get_default_audio_stream()
        if (
            True
            and self.playback_content.audio_stream
            and isinstance(self.playback_content.audio_stream, AudioStream)
            and not isinstance(self.playback_content.audio_stream, OfflineStream)
        ):
            audio_stream = self.playback_content.audio_stream

        self.playback_content.playback_mode = Mode.Music
        self.event_bus.emit(AudioStreamChangeRequest(audio_stream))

    def _spotify_stream_change_request(self, spotify_event: SpotifyStreamChangeRequest):

        spotify_stream = SpotifyStream()
        if hasattr(spotify_event, "track_id"):
            spotify_stream.track_id = spotify_event.track_id

        if (
            spotify_event.is_playback_started()
            and self.playback_content.playback_mode != Mode.Spotify
        ):
            self.playback_content.playback_mode = Mode.Spotify
            self.event_bus.emit(AudioStreamChangedEvent(spotify_stream))

        if (
            spotify_event.is_playback_stopped()
            and self.playback_content.playback_mode != Mode.Idle
        ):
            self._set_to_idle_mode()

        if (
            spotify_event.is_volume_changed()
            and self.playback_content.playback_mode == Mode.Spotify
        ):
            self.event_bus.emit(VolumeChangedEvent())

    def _alarm_triggered(self, _: AlarmTriggeredEvent = None):
        audio_effect = self._get_appropriate_audio_effect()
        self.playback_content.playback_mode = Mode.Alarm
        self.event_bus.emit(VolumeChangeRequest(absolute=audio_effect.volume))
        self.event_bus.emit(AudioStreamChangeRequest(audio_effect.audio_stream))

    def _set_to_idle_mode(self, alarm_stopped_reason: str = None):
        if self.playback_content.playback_mode == Mode.Idle:
            return
        was_alarm = self.playback_content.playback_mode == Mode.Alarm

        if self.playback_content.playback_mode == Mode.Spotify:
            restart_spotify_daemon()

        self.scheduler_service.stop_generic_trigger(SchedulerJobIds.stop_alarm.value)
        self.scheduler_service.stop_generic_trigger(
            SchedulerJobIds.hide_volume_meter.value
        )
        self.playback_content.playback_mode = Mode.Idle
        self.event_bus.emit(AudioStreamChangeRequest(None))

        if was_alarm:
            self.event_bus.emit(
                AlarmStoppedEvent(
                    reason=alarm_stopped_reason,
                    alarm_definition=self.alarm_clock_context.active_alarm_definition,
                )
            )
            self.scheduler_service.stop_generic_trigger(
                SchedulerJobIds.ensure_stable_wifi.value
            )

    def _volume_changed(self, _: VolumeChangedEvent):
        self.start_hide_volume_meter_trigger()

    def get_room_brightness(self):
        return self.brightness_sensor.get_room_brightness()

    def _ignore_offline_stream_events(self, event: SpeakerErrorEvent):
        if event is not None and isinstance(event.audio_stream, OfflineStream):
            return True
        return False

    def _handle_speaker_error(self, event: SpeakerErrorEvent = None):
        if self._ignore_offline_stream_events(event):
            return
        if self.playback_content.playback_mode == Mode.Alarm:
            logger.warning("alarm error occurred: continuing with offline stream")
            self.event_bus.emit(
                AudioStreamChangeRequest(
                    self.alarm_clock_context.config.get_offline_stream()
                )
            )
        else:
            logger.warning("music playback error occurred: switching to idle mode")
            self._set_to_idle_mode()

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
                is_scrolling=self.display_content.is_scrolling,
            ):
                self.event_bus.emit(ForcedDisplayUpdateEvent(suppress_logging=True))

        Controls.action(do)

    def _wifi_status_changed(self, event: WifiStatusChangedEvent):
        if event.is_online:
            self._update_weather_status()
            if self.playback_content.playback_mode == Mode.Alarm:
                self.event_bus.emit(
                    AudioStreamChangeRequest(
                        self.alarm_clock_context.active_alarm_definition.audio_effect.audio_stream
                    )
                )
        else:
            self.alarm_clock_context.environment.current_weather = None
            if self.playback_content.playback_mode == Mode.Alarm:
                self.event_bus.emit(
                    AudioStreamChangeRequest(
                        self.alarm_clock_context.config.get_offline_stream()
                    )
                )

    def _update_weather_status(self):
        def do():
            if not self.alarm_clock_context.environment.is_online:
                self.alarm_clock_context.environment.current_weather = None
                return

            new_weather = GeoLocation().get_current_weather()
            logger.info("weather updating: %s", new_weather)
            self.alarm_clock_context.environment.current_weather = new_weather

        Controls.action(do)

    def _update_wifi_status(self):
        def do():
            is_online = is_internet_available()

            if is_online == self.alarm_clock_context.environment.is_online:
                return

            logger.info("change wifi state, is online: %s", is_online)
            self.event_bus.emit(WifiStatusChangedEvent(is_online))
            self.alarm_clock_context.environment.is_online = is_online

            if (
                True
                and not is_online
                and self.playback_content.playback_mode in [Mode.Music, Mode.Spotify]
            ):
                self._set_to_idle_mode()

        Controls.action(do)

    def _sun_event_occured(self, event: SunEvent):
        def do():
            self.event_bus.emit(SunEventOccurredEvent(event))
            self.alarm_clock_context.environment.is_daytime = event == SunEvent.sunrise
            self.init_sun_event_scheduler(event)

        Controls.action(do, "sun event %s" % event)

    def _get_appropriate_audio_effect(self) -> StreamAudioEffect:
        active_alarm_effect = (
            self.alarm_clock_context.active_alarm_definition.audio_effect
        )
        audio_effect = StreamAudioEffect(volume=active_alarm_effect.volume)
        if (
            False
            or not is_internet_available()
            or self.playback_content.playback_mode
            in [
                Mode.Music,
                Mode.Spotify,
            ]
        ):
            logger.info("adjusting alarm to use offline stream")
            audio_effect.audio_stream = (
                self.alarm_clock_context.config.get_offline_stream()
            )
        else:
            audio_effect.audio_stream = active_alarm_effect.audio_stream

        return audio_effect

    def _ring_alarm(self, alarm_definition: AlarmDefinition):
        def do():

            self._preprocess_ring_alarm(alarm_definition)
            self.event_bus.emit(AlarmTriggeredEvent(alarm_definition))

        Controls.action(do, "ring alarm '%s'" % alarm_definition.alarm_name)

    def _preprocess_ring_alarm(self, alarm_definition: AlarmDefinition):
        self.alarm_clock_context.active_alarm_definition = alarm_definition
        self.scheduler_service.start_generic_trigger(
            SchedulerJobIds.stop_alarm.value,
            datetime.timedelta(
                minutes=self.alarm_clock_context.config.alarm_duration_in_mins
            ),
            func=lambda: self._set_to_idle_mode(alarm_stopped_reason="timeout"),
        )
        self.scheduler_service.add_job(
            self._update_wifi_status,
            trigger="interval",
            seconds=5,
            id=SchedulerJobIds.ensure_stable_wifi.value,
            jobstore=SchedulerStores.default.value,
        )

    def _alarm_stopped_event(self, alarm_stopped_event: AlarmStoppedEvent):
        self.display_content.update_next_alarm(
            self.scheduler_service.get_next_alarm_info()
        )

        alarm_definition = alarm_stopped_event.alarm_definition
        if alarm_definition.is_onetime() and alarm_definition.id >= 0:
            self.alarm_clock_context.config.remove_alarm_definition(alarm_definition.id)
            self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))
        self.alarm_clock_context.active_alarm_definition = None
