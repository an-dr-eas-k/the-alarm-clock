import datetime
import logging
import os
import traceback
from gpiozero import Button, Device
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from domain import (
    AlarmClockState,
    AlarmDefinition,
    AudioStream,
    PlaybackContent,
    DisplayContent,
    Mode,
    StreamAudioEffect,
    Observation,
    Observer,
    Config,
)
from utils.geolocation import GeoLocation, SunEvent
from utils.network import is_internet_available
from utils.os import restart_spotify_daemon
from resources.resources import active_alarm_definition_file

logger = logging.getLogger("tac.controls")

button1Id = 0
button2Id = 5
button3Id = 6
button4Id = 13
alarm_store = "alarm"
default_store = "default"


class Controls(Observer):
    jobstores = {alarm_store: {"type": "memory"}, default_store: {"type": "memory"}}
    scheduler = BackgroundScheduler(jobstores=jobstores)
    buttons = []
    state: AlarmClockState

    def __init__(
        self,
        state: AlarmClockState,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
    ) -> None:
        self.state = state
        self.display_content = display_content
        self.playback_content = playback_content
        self.state.is_daytime = state.geo_location.last_sun_event() == SunEvent.sunrise
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
            self.update_clock,
            "interval",
            seconds=self.state.configuration.refresh_timeout_in_secs,
            id="clock_interval",
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
            trigger=self.state.geo_location.get_sun_event_cron_trigger(event),
            id=event.value,
            jobstore=default_store,
        )

    def update(self, observation: Observation):
        super().update(observation)
        if isinstance(observation.observable, Config):
            self.update_from_config(observation, observation.observable)
        if isinstance(observation.observable, PlaybackContent):
            self.update_from_playback_content(observation, observation.observable)

    def update_from_playback_content(
        self, observation: Observation, playback_content: PlaybackContent
    ):
        if (
            observation.property_name == "volume"
            and not observation.during_registration
        ):
            self.display_content.show_volume_meter = True
            self.start_hide_volume_meter_trigger()

    def start_hide_volume_meter_trigger(self):
        self.start_generic_trigger(
            "hide_volume_meter_trigger",
            datetime.timedelta(seconds=5),
            func=self.display_content.hide_volume_meter,
        )

    def start_generic_trigger(self, job_id: str, duration: datetime.timedelta, func):
        trigger = DateTrigger(run_date=GeoLocation().now() + duration)

        existing_job = self.scheduler.get_job(job_id=job_id)
        if existing_job:
            self.scheduler.reschedule_job(job_id=job_id, trigger=trigger)
        else:
            self.scheduler.add_job(id=job_id, trigger=trigger, func=func)

    def update_from_config(self, observation: Observation, config: Config):
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

    def button_action(action, button_id, event_type: str = "unknown event"):
        Controls.action(action, "button %s %s" % (button_id, event_type))

    def action(action, info: str = None):
        try:
            if info:
                logger.info(info)
            action()
        except:
            logger.error("%s", traceback.format_exc())

    def button1_activated(self):
        Controls.button_action(self.decrease_volume, 1, "activated")

    def button1_held(self):
        Controls.button_action(self.decrease_volume, 1, "held")

    def button2_activated(self):
        Controls.button_action(self.increase_volume, 2, "activated")

    def button2_held(self):
        Controls.button_action(self.increase_volume, 2, "held")

    def button3_activated(self):

        def exit():
            self.scheduler.shutdown(wait=False)
            os._exit(0)

        Controls.button_action(exit, 3, "activated")

    def set_to_idle_mode(self):
        if self.state.mode == Mode.Spotify:
            restart_spotify_daemon()

        if self.state.mode != Mode.Idle:
            self.state.mode = Mode.Idle
            self.state.active_alarm = None

    def button4_activated(self):

        def toggle_stream():

            if self.state.mode in [Mode.Alarm, Mode.Music, Mode.Spotify]:
                self.set_to_idle_mode()
            else:
                if self.playback_content.audio_effect and isinstance(
                    self.playback_content.audio_effect, StreamAudioEffect
                ):
                    self.play_stream(
                        self.playback_content.audio_effect.stream_definition
                    )
                else:
                    self.play_stream_by_id(0)

        Controls.button_action(toggle_stream, 4, "activated")

    def increase_volume(self):
        self.playback_content.increase_volume()
        logger.info("new volume: %s", self.playback_content.volume)

    def decrease_volume(self):
        self.playback_content.decrease_volume()
        logger.info("new volume: %s", self.playback_content.volume)

    def play_stream_by_id(self, stream_id: int):
        streams = self.state.configuration.audio_streams
        stream = next((s for s in streams if s.id == stream_id), streams[0])
        self.play_stream(stream)

    def play_stream(self, audio_stream: AudioStream, volume: float = None):
        self.set_to_idle_mode()

        if volume is None:
            volume = self.playback_content.volume

        self.playback_content.audio_effect = StreamAudioEffect(
            stream_definition=audio_stream, volume=volume
        )
        self.state.mode = Mode.Music

    def configure(self):
        for button in [
            dict(
                b=button1Id,
                ht=0.5,
                hr=True,
                wa=self.button1_activated,
                wh=self.button1_held,
            ),
            dict(
                b=button2Id,
                ht=0.5,
                hr=True,
                wa=self.button2_activated,
                wh=self.button2_held,
            ),
            dict(b=button3Id, wa=self.button3_activated),
            dict(b=button4Id, wa=self.button4_activated),
        ]:
            b = Button(pin=button["b"], bounce_time=0.4)
            if "ht" in button:
                b.hold_time = button["ht"]
            if "hr" in button:
                b.hold_repeat = button["hr"]
            if "wh" in button:
                b.when_held = button["wh"]
            if "wa" in button:
                b.when_activated = button["wa"]
            self.buttons.append(b)

        logger.info("pin factory: %s", Device.pin_factory)

    def update_clock(self):
        def do():
            logger.debug(
                "update show blink segment: %s", not self.state.show_blink_segment
            )
            self.state.show_blink_segment = not self.state.show_blink_segment

        Controls.action(do)

    def update_weather_status(self):
        def do():
            if not self.state.is_online:
                self.display_content.current_weather = None
                return

            new_weather = GeoLocation().get_current_weather()
            logger.info("weather updating: %s", new_weather)
            self.display_content.current_weather = new_weather

        Controls.action(do)

    def update_wifi_status(self):
        def do():
            is_online = is_internet_available()

            if is_online != self.state.is_online:
                logger.info("change wifi state, is online: %s", is_online)
                self.state.is_online = is_online

                if not is_online and self.state in [Mode.Music, Mode.Spotify]:
                    self.set_to_idle_mode()

        Controls.action(do)

    def sun_event_occured(self, event: SunEvent):
        def do():
            self.state.is_daytime = event == SunEvent.sunrise
            self.init_sun_event_scheduler(event)

        Controls.action(do, "sun event %s" % event)

    def ring_alarm(self, alarm_definition: AlarmDefinition):
        def do():
            alarm_effect = alarm_definition.audio_effect

            if self.state.mode in [Mode.Music, Mode.Spotify]:
                alarm_effect = self.state.configuration.get_offline_alarm_effect(
                    alarm_effect.volume
                )

            if alarm_definition.is_one_time():
                self.state.configuration.remove_alarm_definition(alarm_definition.id)

            self.set_to_idle_mode()
            self.state.active_alarm = alarm_definition
            self.state.mode = Mode.Alarm
            self.postprocess_ring_alarm()

        Controls.action(do, "ring alarm %s" % alarm_definition.alarm_name)

    def postprocess_ring_alarm(self):
        self.start_generic_trigger(
            "stop_alarm_trigger",
            datetime.timedelta(minutes=self.state.configuration.alarm_duration_in_mins),
            func=lambda: self.set_to_idle_mode(),
        )

        self.display_content.next_alarm_job = self.get_next_alarm_job()

    def cleanup_alarms(self):
        job: Job
        for job in self.scheduler.get_jobs(jobstore=alarm_store):
            if job.next_run_time is None:
                self.state.configuration.remove_alarm_definition(int(job.id))


class SoftwareControls(Controls):
    def __init__(
        self,
        state: AlarmClockState,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
    ) -> None:
        super().__init__(state, display_content, playback_content)

    def configure(self):
        def key_pressed_action(key):
            logger.debug("pressed %s", key)
            if not hasattr(key, "char"):
                return
            try:
                if key.char == "1":
                    self.button1_activated()
                if key.char == "2":
                    self.button2_activated()
                if key.char == "3":
                    # self.button3_action()
                    pass
                if key.char == "4":
                    self.button4_activated()
            except Exception:
                logger.warning("%s", traceback.format_exc())

        try:
            from pynput.keyboard import Listener

            Listener(on_press=key_pressed_action).start()
        except:
            super().configure()
