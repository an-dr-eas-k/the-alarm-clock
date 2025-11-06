import datetime
from enum import Enum
import logging
import os
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from core.domain.events import (
    AudioEffectChangedEvent,
    AudioStreamChangedEvent,
    ConfigChangedEvent,
    ToggleAudioEvent,
    AlarmEvent,
    RegularDisplayContentUpdateEvent,
    SunEventOccurredEvent,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    AudioStream,
    PlaybackContent,
    DisplayContent,
    Mode,
    RoomBrightness,
    StreamAudioEffect,
    Config,
)
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from utils.geolocation import GeoLocation, SunEvent
from utils.network import is_internet_available
from utils.os import restart_spotify_daemon
from resources.resources import active_alarm_definition_file

logger = logging.getLogger("tac.controls")

alarm_store = "alarm"
default_store = "default"


class SchedulerJobIds(Enum):
    hide_volume_meter = "hide_volume_meter_trigger"
    stop_alarm = "stop_alarm_trigger"


class Controls:
    jobstores = {alarm_store: {"type": "memory"}, default_store: {"type": "memory"}}
    scheduler = BackgroundScheduler(jobstores=jobstores)
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
    ) -> None:
        self.alarm_clock_context = alarm_clock_context
        self.display_content = display_content
        self.playback_content = playback_content
        self.brightness_sensor = brightness_sensor
        self.event_bus = event_bus
        self.event_bus.on(ToggleAudioEvent)(self._toggle_stream)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)
        self.event_bus.on(WifiStatusChangedEvent)(self._wifi_status_changed)
        self.event_bus.on(ConfigChangedEvent)(self._config_changed)
        self.event_bus.on(AlarmEvent)(self._alarm_event)

        self.alarm_clock_context.is_daytime = (
            alarm_clock_context.geo_location.last_sun_event() == SunEvent.sunrise
        )
        self._update_weather_status()
        self._add_scheduler_jobs()
        self.scheduler.start()
        self._print_active_jobs(default_store)

    def consider_failed_alarm(self):
        if os.path.exists(active_alarm_definition_file):
            ad: AlarmDefinition = AlarmDefinition.deserialize(
                active_alarm_definition_file
            )
            logger.info("failed audioeffect found %s", ad.alarm_name)
            self._ring_alarm(ad)

    def _add_scheduler_jobs(self):
        self.scheduler.add_job(
            self._update_display,
            "interval",
            start_date=datetime.datetime.today(),
            seconds=self.alarm_clock_context.config.refresh_timeout_in_secs,
            id="display_interval",
            jobstore=default_store,
        )

        self.scheduler.add_job(
            self.update_wifi_status,
            "interval",
            seconds=60,
            id="wifi_check_interval",
            jobstore=default_store,
        )

        self.scheduler.add_job(
            self._update_weather_status,
            "interval",
            minutes=5,
            id="weather_check_interval",
            jobstore=default_store,
        )

        for event in SunEvent.__members__.values():
            self.init_sun_event_scheduler(event)

    def init_sun_event_scheduler(self, event: SunEvent):
        self.scheduler.add_job(
            lambda: self.sun_event_occured(event),
            trigger=self.alarm_clock_context.geo_location.get_sun_event_cron_trigger(
                event
            ),
            id=event.value,
            jobstore=default_store,
        )

    def start_hide_volume_meter_trigger(self):
        self.start_generic_trigger(
            SchedulerJobIds.hide_volume_meter.value,
            datetime.timedelta(seconds=5),
            func=self.display_content.hide_volume_meter,
        )

    def stop_generic_trigger(self, job_id: str, job_store=default_store):
        if self.scheduler.get_job(job_id=job_id, jobstore=job_store) is not None:
            self.scheduler.remove_job(job_id=job_id, jobstore=job_store)

    def start_generic_trigger(
        self, job_id: str, duration: datetime.timedelta, func, job_store=default_store
    ):
        trigger = DateTrigger(run_date=GeoLocation().now() + duration)

        existing_job = self.scheduler.get_job(job_id=job_id, jobstore=job_store)
        if existing_job:
            self.scheduler.reschedule_job(
                job_id=job_id, trigger=trigger, jobstore=job_store
            )
        else:
            self.scheduler.add_job(
                id=job_id, trigger=trigger, func=func, jobstore=job_store
            )

    def _config_changed(self, event: ConfigChangedEvent):
        config: Config = event.config
        self.scheduler.remove_all_jobs(jobstore=alarm_store)
        alDef: AlarmDefinition
        for alDef in config.alarm_definitions:
            if not alDef.is_active:
                continue
            logger.info("adding job for '%s'", alDef.alarm_name)
            self.scheduler.add_job(
                func=self._ring_alarm,
                args=(alDef,),
                id=f"{alDef.id}",
                jobstore=alarm_store,
                trigger=alDef.to_cron_trigger(),
            )
        self.cleanup_alarms()
        self.display_content.next_alarm_job = self.get_next_alarm_job()
        self._print_active_jobs(alarm_store)

    def get_next_alarm_job(self) -> Job:
        jobs = sorted(
            self.scheduler.get_jobs(jobstore=alarm_store),
            key=lambda job: job.next_run_time,
        )
        return jobs[0] if len(jobs) > 0 else None

    def _print_active_jobs(self, jobstore):
        for job in self.scheduler.get_jobs(jobstore=jobstore):
            if hasattr(job, "next_run_time") and job.next_run_time is not None:
                logger.info(
                    "next runtime for job '%s': %s",
                    job.id,
                    job.next_run_time.strftime(f"%Y-%m-%d %H:%M:%S"),
                )

    def action(action, info: str = None):
        try:
            if info:
                logger.info(info)
            action()
        except:
            logger.error("%s", traceback.format_exc())

    def _toggle_stream(self, _: ToggleAudioEvent):
        if self.playback_content.playback_mode in [
            Mode.Alarm,
            Mode.Music,
            Mode.Spotify,
        ]:
            self.set_to_idle_mode()
        else:
            if self.playback_content.audio_stream and isinstance(
                self.playback_content.audio_stream, AudioStream
            ):
                self._play_stream(self.playback_content.audio_stream)
            else:
                self.play_stream_by_id(0)

    def _alarm_event(self, event: AlarmEvent):
        self.event_bus.emit(
            AudioEffectChangedEvent(event.alarm_definition.audio_effect)
        )

    def set_to_idle_mode(self):
        if self.playback_content.playback_mode == Mode.Idle:
            return

        if self.playback_content.playback_mode == Mode.Spotify:
            restart_spotify_daemon()

        self.stop_generic_trigger(SchedulerJobIds.hide_volume_meter.value)
        self.playback_content.playback_mode = Mode.Idle
        self.event_bus.emit(AudioEffectChangedEvent(None))

    def enter_mode(self):
        self.display_content.mode_state.next_mode_0()

    def _volume_changed(self, _: VolumeChangedEvent):
        self.start_hide_volume_meter_trigger()

    def play_stream_by_id(self, stream_id: int):
        stream = self.alarm_clock_context.config.get_audio_stream_by_id(stream_id)
        self.event_bus.emit(AudioStreamChangedEvent(stream))

    def _play_stream(self, audio_stream: AudioStream):
        self.set_to_idle_mode()

        self.playback_content.playback_mode = Mode.Music
        self.event_bus.emit(AudioStreamChangedEvent(audio_stream))

    def configure(self):
        pass

    def get_room_brightness(self):
        return self.brightness_sensor.get_room_brightness()

    def _update_display(self):

        def do():
            logger.debug("update display")
            current_second = GeoLocation().now().second
            new_blink_state = self.alarm_clock_context.show_blink_segment

            if self._previous_second != current_second:
                new_blink_state = not self.alarm_clock_context.show_blink_segment
                self._previous_second = current_second

            b = RoomBrightness(self.get_room_brightness())
            if self.alarm_clock_context.update_state(
                new_blink_state,
                b,
                self.display_content.is_scrolling,
            ):
                self.event_bus.emit(
                    RegularDisplayContentUpdateEvent(
                        show_blink_segment=new_blink_state,
                        room_brightness=b,
                    )
                )

        Controls.action(do)

    def _wifi_status_changed(self, event: WifiStatusChangedEvent):
        if event.is_online:
            self._update_weather_status()
        else:
            self.display_content.current_weather = None

    def _update_weather_status(self):
        def do():
            if not self.alarm_clock_context.is_online:
                self.display_content.current_weather = None
                return

            new_weather = GeoLocation().get_current_weather()
            logger.info("weather updating: %s", new_weather)
            self.display_content.current_weather = new_weather

        Controls.action(do)

    def update_wifi_status(self):
        def do():
            is_online = is_internet_available()

            if is_online != self.alarm_clock_context.is_online:
                logger.info("change wifi state, is online: %s", is_online)
                self.event_bus.emit(WifiStatusChangedEvent(is_online))
                self.alarm_clock_context.is_online = is_online

                if not is_online and self.playback_content.playback_mode in [
                    Mode.Music,
                    Mode.Spotify,
                ]:
                    self.set_to_idle_mode()

        Controls.action(do)

    def sun_event_occured(self, event: SunEvent):
        def do():
            self.event_bus.emit(SunEventOccurredEvent(event))
            self.alarm_clock_context.is_daytime = event == SunEvent.sunrise
            self.init_sun_event_scheduler(event)

        Controls.action(do, "sun event %s" % event)

    def _ring_alarm(self, alarm_definition: AlarmDefinition):
        def do():
            if self.playback_content.playback_mode in [Mode.Music, Mode.Spotify]:
                alarm_definition.audio_effect = StreamAudioEffect(
                    audio_stream=self.alarm_clock_context.config.get_offline_stream(),
                    volume=self.playback_content.volume,
                )

            if alarm_definition.is_onetime():
                self.alarm_clock_context.config.remove_alarm_definition(
                    alarm_definition.id
                )

            self.set_to_idle_mode()
            self.playback_content.playback_mode = Mode.Alarm
            self.event_bus.emit(AlarmEvent(alarm_definition))
            self.postprocess_ring_alarm()

        Controls.action(do, "ring alarm %s" % alarm_definition.alarm_name)

    def postprocess_ring_alarm(self):
        self.start_generic_trigger(
            SchedulerJobIds.stop_alarm.value,
            datetime.timedelta(
                minutes=self.alarm_clock_context.config.alarm_duration_in_mins
            ),
            func=self.set_to_idle_mode,
        )

        self.display_content.next_alarm_job = self.get_next_alarm_job()

    def cleanup_alarms(self):
        job: Job
        for job in self.scheduler.get_jobs(jobstore=alarm_store):
            if job.next_run_time is None:
                self.alarm_clock_context.config.remove_alarm_definition(int(job.id))
