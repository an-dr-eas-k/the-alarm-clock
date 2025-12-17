import datetime
import logging
import os
from core.application.basic_audio_service import BasicAudioService
from core.domain.events import (
    PlaybackChangedEvent,
    ConfigChangedEvent,
    StartupFinishedEvent,
    AlarmTriggeredEvent,
    PreAlarmTriggeredEvent,
    AlarmStoppedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    NextAlarmInfo,
    PlaybackContent,
    Mode,
    SchedulerJobIds,
    StreamAudioEffect,
    Config,
)
from core.interface.display.display_content import DisplayContent
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from core.infrastructure.scheduler import SchedulerService, SchedulerStores
from resources.resources import active_alarm_definition_file
from utils.os_interactions import OSInteraction

logger = logging.getLogger("tac.core.application.alarm_audio_service")


class AlarmAudioService(BasicAudioService):
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
        logger.info(
            "next alarm info updated: %s",
            next_alarm_info if next_alarm_info.next_run_time else "none",
        )

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

        if event.alarm_definition.is_onetime() and event.alarm_definition.id >= 0:
            self.alarm_clock_context.config.remove_alarm_definition(
                event.alarm_definition.id
            )
            self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))
        else:
            self.update_next_alarm()

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
