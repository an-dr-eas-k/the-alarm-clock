import datetime
from enum import Enum
import logging
import os
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    AudioStream,
    PlaybackContent,
    DisplayContent,
    Mode,
    RoomBrightness,
    StreamAudioEffect,
    TACEvent,
    TACEventSubscriber,
    Config,
)
from core.infrastructure.brightness_sensor import IBrightnessSensor
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


class Controls(TACEventSubscriber):
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
    ) -> None:
        self.alarm_clock_context = alarm_clock_context
        self.display_content = display_content
        self.playback_content = playback_content
        self.brightness_sensor = brightness_sensor

        self.alarm_clock_context.is_daytime = (
            alarm_clock_context.geo_location.last_sun_event() == SunEvent.sunrise
        )
        self.update_weather_status()
        self.add_scheduler_jobs()
        self.scheduler.start()
        self.print_active_jobs(default_store)

    def consider_failed_alarm(self):
        if os.path.exists(active_alarm_definition_file):
            ad: AlarmDefinition = AlarmDefinition.deserialize(
                active_alarm_definition_file
            )
            logger.info("failed audioeffect found %s", ad.alarm_name)
            self.ring_alarm(ad)

    def add_scheduler_jobs(self):
        self.scheduler.add_job(
            self.update_display,
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
            self.update_weather_status,
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

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if isinstance(observation.subscriber, Config):
            self.update_from_config(observation, observation.subscriber)
        if isinstance(observation.subscriber, PlaybackContent):
            self.update_from_playback_content(observation, observation.subscriber)
        # Volume adjustments were previously tied to hardware triggers passed through AlarmClockStateMachine.
        # TODO: replace with hardware->domain trigger mapper publishing dedicated domain events.
        if observation.property_name == "mode" and observation.reason in [
            "rotary_clockwise",
            "rotary_counter_clockwise",
            "invoke_button",
        ]:
            if observation.reason == "rotary_clockwise":
                self.increase_volume()
            elif observation.reason == "rotary_counter_clockwise":
                self.decrease_volume()
            elif observation.reason == "invoke_button":
                self.toggle_stream()

    def update_from_playback_content(
        self, observation: TACEvent, playback_content: PlaybackContent
    ):
        if (
            observation.property_name == "volume"
            and not observation.during_registration
        ):
            self.display_content.show_volume_meter = True
            self.start_hide_volume_meter_trigger()

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

    def update_from_config(self, observation: TACEvent, config: Config):
        if observation.property_name == "alarm_definitions":
            self.scheduler.remove_all_jobs(jobstore=alarm_store)
            alDef: AlarmDefinition
            for alDef in config.alarm_definitions:
                if not alDef.is_active:
                    continue
                logger.info("adding job for '%s'", alDef.alarm_name)
                self.scheduler.add_job(
                    func=self.ring_alarm,
                    args=(alDef,),
                    id=f"{alDef.id}",
                    jobstore=alarm_store,
                    trigger=alDef.to_cron_trigger(),
                )
            self.cleanup_alarms()
            self.display_content.next_alarm_job = self.get_next_alarm_job()
            self.print_active_jobs(alarm_store)
        if observation.property_name == "is_online" and observation.new_value:
            self.update_weather_status()

    def get_next_alarm_job(self) -> Job:
        jobs = sorted(
            self.scheduler.get_jobs(jobstore=alarm_store),
            key=lambda job: job.next_run_time,
        )
        return jobs[0] if len(jobs) > 0 else None

    def print_active_jobs(self, jobstore):
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

    def toggle_stream(self):
        if self.alarm_clock_context.mode in [Mode.Alarm, Mode.Music, Mode.Spotify]:
            self.set_to_idle_mode()
        else:
            if self.playback_content.audio_effect and isinstance(
                self.playback_content.audio_effect, StreamAudioEffect
            ):
                self.play_stream(self.playback_content.audio_effect.stream_definition)
            else:
                self.play_stream_by_id(0)

    def set_to_idle_mode(self):
        if self.alarm_clock_context.mode == Mode.Spotify:
            restart_spotify_daemon()

        if self.alarm_clock_context.mode != Mode.Idle:
            self.stop_generic_trigger(SchedulerJobIds.hide_volume_meter.value)
            self.display_content.hide_volume_meter()
            self.alarm_clock_context.mode = Mode.Idle
            self.alarm_clock_context.active_alarm = None

    def enter_mode(self):
        self.display_content.mode_state.next_mode_0()

    def increase_volume(self):
        self.playback_content.increase_volume()
        logger.info("new volume: %s", self.playback_content.volume)

    def decrease_volume(self):
        self.playback_content.decrease_volume()
        logger.info("new volume: %s", self.playback_content.volume)

    def play_stream_by_id(self, stream_id: int):
        streams = self.alarm_clock_context.config.audio_streams
        stream = next((s for s in streams if s.id == stream_id), streams[0])
        self.play_stream(stream)

    def play_stream(self, audio_stream: AudioStream, volume: float = None):
        self.set_to_idle_mode()

        if volume is None:
            volume = self.playback_content.volume

        self.playback_content.audio_effect = StreamAudioEffect(
            stream_definition=audio_stream, volume=volume
        )
        self.alarm_clock_context.mode = Mode.Music

    def configure(self):
        pass

    def get_room_brightness(self):
        return self.brightness_sensor.get_room_brightness()

    def update_display(self):

        def do():
            logger.debug("update display")
            current_second = GeoLocation().now().second
            new_blink_state = self.alarm_clock_context.show_blink_segment
            if self._previous_second != current_second:
                new_blink_state = not self.alarm_clock_context.show_blink_segment
                self._previous_second = current_second

            self.alarm_clock_context.update_state(
                new_blink_state,
                RoomBrightness(self.get_room_brightness()),
                self.display_content.is_scrolling,
            )

        Controls.action(do)

    def update_weather_status(self):
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
                self.alarm_clock_context.is_online = is_online

                if not is_online and self.alarm_clock_context.mode in [
                    Mode.Music,
                    Mode.Spotify,
                ]:
                    self.set_to_idle_mode()

        Controls.action(do)

    def sun_event_occured(self, event: SunEvent):
        def do():
            self.alarm_clock_context.is_daytime = event == SunEvent.sunrise
            self.init_sun_event_scheduler(event)

        Controls.action(do, "sun event %s" % event)

    def ring_alarm(self, alarm_definition: AlarmDefinition):
        def do():
            if self.alarm_clock_context.mode in [Mode.Music, Mode.Spotify]:
                alarm_definition.audio_effect = (
                    self.alarm_clock_context.config.get_offline_alarm_effect(
                        alarm_definition.audio_effect.volume
                    )
                )

            if alarm_definition.is_onetime():
                self.alarm_clock_context.config.remove_alarm_definition(
                    alarm_definition.id
                )

            self.set_to_idle_mode()
            self.alarm_clock_context.active_alarm = alarm_definition
            self.alarm_clock_context.mode = Mode.Alarm
            self.postprocess_ring_alarm()

        Controls.action(do, "ring alarm %s" % alarm_definition.alarm_name)

    def postprocess_ring_alarm(self):
        self.start_generic_trigger(
            SchedulerJobIds.stop_alarm.value,
            datetime.timedelta(
                minutes=self.alarm_clock_context.config.alarm_duration_in_mins
            ),
            func=lambda: self.set_to_idle_mode(),
        )

        self.display_content.next_alarm_job = self.get_next_alarm_job()

    def cleanup_alarms(self):
        job: Job
        for job in self.scheduler.get_jobs(jobstore=alarm_store):
            if job.next_run_time is None:
                self.alarm_clock_context.config.remove_alarm_definition(int(job.id))
