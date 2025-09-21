import datetime
from enum import Enum
import logging
import os
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from core.domain.model import (
    AlarmClockState,
    AlarmDefinition,
    AudioStream,
    HwButton,
    PlaybackContent,
    DisplayContent,
    Mode,
    RoomBrightness,
    StreamAudioEffect,
    TACEvent,
    TACEventSubscriber,
    Config,
)
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
    state: AlarmClockState
    rotary_encoder_manager = None
    _previous_second = GeoLocation().now().second

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
            self.update_display,
            "interval",
            start_date=datetime.datetime.today(),
            seconds=self.state.config.refresh_timeout_in_secs,
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
            trigger=self.state.geo_location.get_sun_event_cron_trigger(event),
            id=event.value,
            jobstore=default_store,
        )

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if isinstance(observation.subscriber, Config):
            self.update_from_config(observation, observation.subscriber)
        if isinstance(observation.subscriber, PlaybackContent):
            self.update_from_playback_content(observation, observation.subscriber)

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

    def button_action(self, hwButton: HwButton):
        self.state.state_machine.do_state_transition(hwButton)
        if not hwButton.action:
            return
        Controls.action(hwButton.action, hwButton.__str__())

    def action(action, info: str = None):
        try:
            if info:
                logger.info(info)
            action()
        except:
            logger.error("%s", traceback.format_exc())

    def rotary_counter_clockwise(self):
        self.button_action(
            HwButton("rotary_left", "activated", action=self.decrease_volume)
        )

    def rotary_clockwise(self):
        self.button_action(
            HwButton("rotary_right", "activated", action=self.increase_volume)
        )

    def mode_button_triggered(self):
        self.button_action(HwButton("mode_button", "activated"))

    def invoke_button_triggered(self):

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

        self.button_action(HwButton("invoke_button", "activated", action=toggle_stream))

    def set_to_idle_mode(self):
        if self.state.mode == Mode.Spotify:
            restart_spotify_daemon()

        if self.state.mode != Mode.Idle:
            self.stop_generic_trigger(SchedulerJobIds.hide_volume_meter.value)
            self.display_content.hide_volume_meter()
            self.state.mode = Mode.Idle
            self.state.active_alarm = None

    def enter_mode(self):
        self.display_content.mode_state.next_mode_0()

    def increase_volume(self):
        self.playback_content.increase_volume()
        logger.info("new volume: %s", self.playback_content.volume)

    def decrease_volume(self):
        self.playback_content.decrease_volume()
        logger.info("new volume: %s", self.playback_content.volume)

    def play_stream_by_id(self, stream_id: int):
        streams = self.state.config.audio_streams
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
        pass

    def get_room_brightness(self):
        pass

    def update_display(self):

        def do():
            logger.debug("update display")
            current_second = GeoLocation().now().second
            new_blink_state = self.state.show_blink_segment
            if self._previous_second != current_second:
                new_blink_state = not self.state.show_blink_segment
                self._previous_second = current_second

            self.state.update_state(
                new_blink_state,
                RoomBrightness(self.get_room_brightness()),
                self.display_content.is_scrolling,
            )

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
            if self.state.mode in [Mode.Music, Mode.Spotify]:
                alarm_definition.audio_effect = (
                    self.state.config.get_offline_alarm_effect(
                        alarm_definition.audio_effect.volume
                    )
                )

            if alarm_definition.is_onetime():
                self.state.config.remove_alarm_definition(alarm_definition.id)

            self.set_to_idle_mode()
            self.state.active_alarm = alarm_definition
            self.state.mode = Mode.Alarm
            self.postprocess_ring_alarm()

        Controls.action(do, "ring alarm %s" % alarm_definition.alarm_name)

    def postprocess_ring_alarm(self):
        self.start_generic_trigger(
            SchedulerJobIds.stop_alarm.value,
            datetime.timedelta(minutes=self.state.config.alarm_duration_in_mins),
            func=lambda: self.set_to_idle_mode(),
        )

        self.display_content.next_alarm_job = self.get_next_alarm_job()

    def cleanup_alarms(self):
        job: Job
        for job in self.scheduler.get_jobs(jobstore=alarm_store):
            if job.next_run_time is None:
                self.state.config.remove_alarm_definition(int(job.id))


class HardwareControls(Controls):
    def __init__(
        self,
        state: AlarmClockState,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
    ) -> None:

        super().__init__(state, display_content, playback_content)

    def configure(self):
        from core.infrastructure.mcp23017.buttons import ButtonsManager
        from core.infrastructure.mcp23017.rotary_encoder import RotaryEncoderManager

        self.button_manager = ButtonsManager(
            mode_channel_callback=self.mode_button_triggered,
            invoke_channel_callback=self.invoke_button_triggered,
        )
        self.rotary_encoder_manager = RotaryEncoderManager(
            on_clockwise=self.rotary_clockwise,
            on_counter_clockwise=self.rotary_counter_clockwise,
        )

    def get_room_brightness(self):
        from core.infrastructure.bh1750 import get_room_brightness

        return get_room_brightness()


class SoftwareControls(Controls):
    simulated_brightness: int = 10000

    def __init__(
        self,
        state: AlarmClockState,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
    ) -> None:
        super().__init__(state, display_content, playback_content)

    def get_room_brightness(self):
        return self.simulated_brightness

    def configure(self):
        def key_pressed_action(key):
            logger.debug("pressed %s", key)
            if not hasattr(key, "char"):
                return
            try:
                if key.char == "1":
                    self.rotary_counter_clockwise()
                if key.char == "2":
                    self.rotary_clockwise()
                if key.char == "3":
                    self.mode_button_triggered()
                if key.char == "4":
                    self.invoke_button_triggered()
                if key.char == "5":
                    brightness_examples = [0, 1, 3, 10, 10000]
                    self.simulated_brightness = brightness_examples[
                        (brightness_examples.index(self.simulated_brightness) + 1)
                        % len(brightness_examples)
                    ]
                    logger.info("simulated brightness: %s", self.simulated_brightness)

            except Exception:
                logger.warning("%s", traceback.format_exc())

        try:
            from pynput.keyboard import Listener

            Listener(on_press=key_pressed_action).start()
        except:
            super().configure()
