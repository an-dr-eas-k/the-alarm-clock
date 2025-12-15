import datetime
import logging
import os
import traceback
from apscheduler.job import Job
from core.domain.events import (
    PlaybackChangedEvent,
    ConfigChangedEvent,
    SpeakerErrorEvent,
    SpotifyApiEvent,
    StartupFinishedEvent,
    ToggleAudioRequest,
    AlarmTriggeredEvent,
    PreAlarmTriggeredEvent,
    AlarmStoppedEvent,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    AudioStream,
    NextAlarmInfo,
    OfflineStream,
    PlaybackContent,
    Mode,
    SchedulerJobIds,
    SpotifyStream,
    StreamAudioEffect,
    Config,
)
from core.interface.display.display_content import DisplayContent
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from core.infrastructure.scheduler import SchedulerService, SchedulerStores
from resources.resources import active_alarm_definition_file
from utils.os_interactions import OSInteraction

logger = logging.getLogger("tac.core.application.controls")


def safe_action(
    action, info_msg: str = None, debug_msg: str = None, logger: logging.Logger = None
):
    try:
        if logger:
            if debug_msg:
                logger.debug(debug_msg)
            if info_msg:
                logger.info(info_msg)
        else:
            raise ValueError("logger must be provided to save_action")
        action()
    except:
        logger.error("%s", traceback.format_exc())


class BasicAudioControls:
    scheduler_service: SchedulerService
    alarm_clock_context: AlarmClockContext

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        brightness_sensor: IBrightnessSensor,
        event_bus: EventBus,
        scheduler_service: SchedulerService,
        os_interaction: OSInteraction,
    ) -> None:
        self.alarm_clock_context = alarm_clock_context
        self.display_content = display_content
        self.playback_content = playback_content
        self.brightness_sensor = brightness_sensor
        self.event_bus = event_bus
        self.scheduler_service = scheduler_service
        self.os_interaction = os_interaction
        self.event_bus.on(ToggleAudioRequest)(self._toggle_stream)
        self.event_bus.on(WifiStatusChangedEvent)(self._wifi_status_changed)
        self.event_bus.on(ConfigChangedEvent)(self._config_changed)
        self.event_bus.on(SpeakerErrorEvent)(self._handle_speaker_error)
        self.event_bus.on(SpotifyApiEvent)(self._spotify_stream_change_request)

    def _toggle_stream(self, _: ToggleAudioRequest):

        if self.playback_content.playback_mode != Mode.Idle:
            self.event_bus.emit(PlaybackChangedEvent(Mode.Idle))
            return

        audio_stream = self.alarm_clock_context.config.get_default_audio_stream()
        if (
            True
            and self.playback_content.audio_stream
            and isinstance(self.playback_content.audio_stream, AudioStream)
            and not isinstance(self.playback_content.audio_stream, OfflineStream)
        ):
            audio_stream = self.playback_content.audio_stream

        self.event_bus.emit(PlaybackChangedEvent(Mode.Music, audio_stream))

    def _spotify_stream_change_request(self, spotify_event: SpotifyApiEvent):

        spotify_stream = SpotifyStream()
        if hasattr(spotify_event, "track_id"):
            spotify_stream.track_id = spotify_event.track_id

        if (
            spotify_event.is_playback_started()
            and self.playback_content.playback_mode != Mode.Spotify
        ):
            self.event_bus.emit(PlaybackChangedEvent(Mode.Spotify, spotify_stream))

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

    def _set_to_idle_mode(self):
        if self.playback_content.playback_mode == Mode.Idle:
            return

        self.event_bus.emit(PlaybackChangedEvent(Mode.Idle))

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
                PlaybackChangedEvent(
                    Mode.Alarm, self.alarm_clock_context.config.get_offline_stream()
                )
            )
        else:
            logger.warning("music playback error occurred: switching to idle mode")
            self._set_to_idle_mode()

    def _wifi_status_changed(self, event: WifiStatusChangedEvent):
        if event.is_online:
            if self.playback_content.playback_mode == Mode.Alarm:
                self.event_bus.emit(
                    PlaybackChangedEvent(
                        Mode.Alarm,
                        self.alarm_clock_context.active_alarm_definition.audio_effect.audio_stream,
                    )
                )
        else:
            if self.playback_content.playback_mode == Mode.Alarm:
                self.event_bus.emit(
                    PlaybackChangedEvent(
                        Mode.Alarm, self.alarm_clock_context.config.get_offline_stream()
                    )
                )

            if not event.is_online and self.playback_content.playback_mode in [
                Mode.Music,
                Mode.Spotify,
            ]:
                self._set_to_idle_mode()


class AlarmAudioControls(BasicAudioControls):
    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        brightness_sensor: IBrightnessSensor,
        event_bus: EventBus,
        scheduler_service: SchedulerService,
        os_interaction: OSInteraction,
    ) -> None:
        super().__init__(
            alarm_clock_context,
            display_content,
            playback_content,
            brightness_sensor,
            event_bus,
            scheduler_service,
            os_interaction,
        )
        self.event_bus.on(AlarmTriggeredEvent)(self._alarm_triggered)
        self.event_bus.on(AlarmStoppedEvent)(self._alarm_stopped_event)
        self.event_bus.on(StartupFinishedEvent)(self._handle_startup_finished)

    def consider_failed_alarm(self):
        if os.path.exists(active_alarm_definition_file):
            ad: AlarmDefinition = AlarmDefinition.deserialize(
                active_alarm_definition_file
            )
            ad.id = -1
            logger.info("failed audioeffect found %s", ad.alarm_name)
            self._ring_alarm(ad)

    def _handle_startup_finished(self, _: StartupFinishedEvent):
        self.consider_failed_alarm()

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
                job_id=f"{alDef.id}",
                jobstore=SchedulerStores.alarm.value,
                **alDef.get_cron_args(),
            )
        self.scheduler_service.cleanup_alarms(config)
        self.update_next_alarm()

    def update_next_alarm(self):
        next_alarm_info: NextAlarmInfo = self.scheduler_service.get_next_alarm_info()
        if next_alarm_info.next_run_time is not None:
            self.scheduler_service.add_or_replace_date_job(
                func=self._trigger_pre_alarm,
                args=[next_alarm_info.alarm_definition],
                run_date=next_alarm_info.next_run_time
                - datetime.timedelta(
                    minutes=self.alarm_clock_context.config.pre_alarm_trigger_in_mins
                ),
                job_id=SchedulerJobIds.pre_alarm.value,
                jobstore=SchedulerStores.default.value,
            )
        self.display_content.update_next_alarm(next_alarm_info)
        logger.info("next alarm info updated: %s", next_alarm_info)

    def _alarm_triggered(self, event: AlarmTriggeredEvent = None):
        self._preprocess_ring_alarm(event.alarm_definition)
        audio_effect = self._get_appropriate_alarm_effect()
        self.event_bus.emit(
            PlaybackChangedEvent(
                Mode.Alarm,
                audio_effect.audio_stream,
                absolute_volume=audio_effect.volume,
            )
        )
        self.update_next_alarm()

        if event.alarm_definition.is_onetime() and event.alarm_definition.id >= 0:
            self.alarm_clock_context.config.remove_alarm_definition(
                event.alarm_definition.id
            )
            self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))

    def _get_appropriate_alarm_effect(self) -> StreamAudioEffect:
        active_alarm_effect = (
            self.alarm_clock_context.active_alarm_definition.audio_effect
        )
        audio_effect = StreamAudioEffect(volume=active_alarm_effect.volume)
        if (
            False
            or not self.os_interaction.is_internet_available()
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

    def _trigger_pre_alarm(self, alarm_definition: AlarmDefinition):
        def do():
            self.event_bus.emit(PreAlarmTriggeredEvent(alarm_definition))

        safe_action(
            do, "trigger pre-alarm '%s'" % alarm_definition.alarm_name, logger=logger
        )

    def _ring_alarm(self, alarm_definition: AlarmDefinition):
        def do():

            self.event_bus.emit(AlarmTriggeredEvent(alarm_definition))

        safe_action(do, "ring alarm '%s'" % alarm_definition.alarm_name, logger=logger)

    def _preprocess_ring_alarm(self, alarm_definition: AlarmDefinition):
        self.alarm_clock_context.active_alarm_definition = alarm_definition
        self.scheduler_service.start_generic_trigger(
            SchedulerJobIds.stop_alarm.value,
            datetime.timedelta(
                minutes=self.alarm_clock_context.config.alarm_duration_in_mins
            ),
            func=self._set_to_idle_mode,
        )

    def _alarm_stopped_event(self, _: AlarmStoppedEvent):
        self.scheduler_service.stop_generic_trigger(SchedulerJobIds.stop_alarm.value)
        self.alarm_clock_context.active_alarm_definition = None
