from dataclasses import dataclass
from datetime import time, timedelta
import datetime
import json
import os
from typing import List
from apscheduler.job import Job
from enum import Enum
import logging

import jsonpickle
from apscheduler.triggers.cron import CronTrigger
from utils.extensions import Value, get_timedelta_to_alarm, respect_ranges

from utils.events import TACEventPublisher, TACEvent, TACEventSubscriber
from utils.geolocation import GeoLocation, Weather
from resources.resources import alarms_dir, default_volume
from utils.singleton import singleton
from utils.sound_device import TACSoundDevice
from utils.state_machine import State, StateMachine, StateTransition, Trigger

logger = logging.getLogger("tac.domain")


def try_update(object, property_name: str, value: str) -> bool:
    if hasattr(object, property_name):
        attr_value = getattr(object, property_name)
        attr_type = type(attr_value)
        if attr_type == bool:
            value = value.lower() in ["on", "yes", "true", "t", "1"]
        else:
            value = attr_type(value) if len(value) > 0 else None
        if value != attr_value:
            setattr(object, property_name, value)
            if isinstance(object, TACEventPublisher):
                object.publish(property=property_name)
        return True
    return False


class StreamContent:

    name: str

    def __init__(self, dict: dict):
        for key, value in dict.items():
            setattr(self, key, value)


class SpotifyAlbum(StreamContent):
    pass


class SpotifyArtist(StreamContent):
    pass


class SpotifyTrack(StreamContent):

    album: SpotifyAlbum
    artists: List[SpotifyArtist]


class LibreSpotifyEvent(StreamContent):

    player_event: str = None
    track_id: str
    old_track_id: str
    duration_ms: str
    position_ms: str
    volume: str
    sink_status: str

    def is_playback_started(self) -> bool:
        return self.player_event in ["playing", "started", "changed"]

    def is_playback_stopped(self) -> bool:
        return self.player_event in ["stopped", "paused"]

    def is_volume_changed(self) -> bool:
        return self.player_event in ["volume_set"]

    def __str__(self):
        return json.dumps(self.__dict__)


class Mode(Enum):
    Boot = 0
    Idle = 1
    Alarm = 2
    Music = 3
    Spotify = 4


class Weekday(Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class RoomBrightness(Value[float]):
    def __init__(self, room_brightness: float):
        super().__init__(room_brightness)

    def is_highly_dimmed(self) -> bool:
        return self.value < 0.01

    def __ne__(self, other: "RoomBrightness"):
        return not self == other

    def __eq__(self, other: "RoomBrightness"):
        return self.get_grayscale_value() == other.get_grayscale_value()

    def get_grayscale_value(self, min_value: int = 0, max_value: int = 15) -> int:
        x = max_value
        if self.value < 15:
            x = 10
        if self.value < 6:
            x = 7
        if self.value < 2:
            x = 3

        if self.is_highly_dimmed():
            x = 0
        return respect_ranges(x, min_value, max_value)


@dataclass
class Style:
    background_grayscale_16: int
    foreground_grayscale_16: int
    be_bold: bool


class VisualEffect:

    def is_active(self, alarm_in_minutes: int) -> bool:
        return alarm_in_minutes <= 8

    def get_style(self, alarm_in_minutes: int):
        if alarm_in_minutes <= 2:
            return Style(
                background_grayscale_16=15, foreground_grayscale_16=0, be_bold=True
            )
        if alarm_in_minutes <= 4:
            return Style(
                background_grayscale_16=7, foreground_grayscale_16=0, be_bold=True
            )

        return Style(
            background_grayscale_16=0, foreground_grayscale_16=15, be_bold=True
        )


@dataclass
class AudioStream:
    stream_name: str
    stream_url: str
    id: int = -1

    def __str__(self):
        return f"stream_name: {self.stream_name}, stream_url: {self.stream_url}"


class AudioEffect:

    def __init__(self, volume: float = None):
        self.volume = volume

    def __str__(self):
        return f"volume: {self.volume}"

    def title(self):
        return None


class StreamAudioEffect(AudioEffect):
    stream_definition: AudioStream = None

    def __init__(self, stream_definition: AudioStream = None, volume: float = None):
        super().__init__(volume)
        self.stream_definition = stream_definition

    def __str__(self):
        return f"stream_definition: {self.stream_definition} {super().__str__()}"

    def title(self):
        return self.stream_definition.stream_name


@singleton
class OfflineAlarmEffect(StreamAudioEffect):

    def title(self):
        return "Offline Alarm"


class SpotifyAudioEffect(TACEventPublisher, AudioEffect):
    spotify_event: LibreSpotifyEvent = None
    track_name: str = "Spotify"

    @property
    def track_id(self) -> str:
        return self._track_id

    @track_id.setter
    def track_id(self, value: str):
        self._track_id = value
        self.publish(property="track_id")

    def __init__(self, volume: float = None):
        TACEventPublisher.__init__(self)
        AudioEffect.__init__(self, volume)

    def __str__(self):
        return f"track_id: {self.track_id}, spotify_event: {self.spotify_event} {super().__str__()}"

    def title(self):
        return self.track_name


class AlarmDefinition:
    id: int
    hour: int
    min: int
    weekdays: List[Weekday]
    date: datetime
    alarm_name: str
    is_active: bool
    visual_effect: VisualEffect
    _audio_effect: AudioEffect

    def to_cron_trigger(self) -> CronTrigger:
        if self.weekdays is not None and len(self.weekdays) > 0:
            return CronTrigger(
                day_of_week=",".join(
                    [str(Weekday[wd].value - 1) for wd in self.weekdays]
                ),
                hour=self.hour,
                minute=self.min,
            )
        elif self.date is not None:
            return CronTrigger(
                start_date=self.date,
                end_date=self.date + timedelta(days=1),
                hour=self.hour,
                minute=self.min,
            )

    def to_time_string(self) -> str:
        return time(hour=self.hour, minute=self.min).strftime("%H:%M")

    def to_weekdays_string(self) -> str:
        if self.weekdays is not None and len(self.weekdays) > 0:
            return ", ".join(
                [Weekday[wd].name.lower().capitalize() for wd in self.weekdays]
            )
        elif self.date is not None:
            return self.date.strftime("%Y-%m-%d")

    def set_future_date(self, hour: int, minute: int):
        now = GeoLocation().now()
        target = now.replace(hour=hour, minute=minute)
        if target < now:
            target = target + timedelta(days=1)
        self.date = target.date()
        self.weekdays = None

    def is_one_time(self) -> bool:
        return self.date is not None

    @property
    def audio_effect(self) -> AudioEffect:
        return self._audio_effect

    @audio_effect.setter
    def audio_effect(self, value: AudioEffect):
        self._audio_effect = value

    def serialize(self, alarm_definition_file: str):
        with open(alarm_definition_file, "w") as file:
            file.write(jsonpickle.encode(self, indent=2))

    def deserialize(alarm_definition_file: str):
        logger.debug(
            "initializing AlarmDefinition from file: %s", alarm_definition_file
        )
        with open(alarm_definition_file, "r") as file:
            file_contents = file.read()

        persisted_alarm_definition: AlarmDefinition = jsonpickle.decode(file_contents)
        return persisted_alarm_definition


class Config(TACEventPublisher):

    clock_format_string: str
    blink_segment: str
    offline_alarm: AudioStream
    alarm_duration_in_mins: int
    refresh_timeout_in_secs: float
    powernap_duration_in_mins: int
    default_volume: float = default_volume
    use_analog_clock: bool
    alarm_preview_hours: int
    debug_level: int

    @property
    def alarm_definitions(self) -> List[AlarmDefinition]:
        return self._alarm_definitions

    @property
    def audio_streams(self) -> List[AudioStream]:
        return self._audio_streams

    @property
    def local_alarm_file(self) -> str:
        return self.offline_alarm.stream_url

    @local_alarm_file.setter
    def local_alarm_file(self, value: str):
        self.offline_alarm = AudioStream(stream_name="Offline Alarm", stream_url=value)
        self.publish(property="blink_segment")

    def __init__(self):
        logger.debug("initializing default config")
        self._alarm_definitions = []
        self._audio_streams = []
        self.ensure_valid_config()
        super().__init__()

    def add_alarm_definition(self, value: AlarmDefinition):
        self._alarm_definitions = self._append_item_with_id(
            value, self._alarm_definitions
        )
        self.publish(property="alarm_definitions")

    def remove_alarm_definition(self, id: int):
        self._alarm_definitions = [
            alarm_def for alarm_def in self._alarm_definitions if alarm_def.id != id
        ]
        self.publish(property="alarm_definitions")

    def get_alarm_definition(self, id: int) -> AlarmDefinition:
        return next(
            (alarm for alarm in self._alarm_definitions if alarm.id == id), None
        )

    def get_audio_stream(self, id: int) -> AudioStream:
        return next((stream for stream in self._audio_streams if stream.id == id), None)

    def add_audio_stream(self, value: AudioStream):
        self._audio_streams = self._append_item_with_id(value, self._audio_streams)
        self.publish(property="audio_streams")

    def remove_audio_stream(self, id: int):
        self._audio_streams = [
            stream_def for stream_def in self._audio_streams if stream_def.id != id
        ]
        self.publish(property="audio_streams")

    def _append_item_with_id(self, item_with_id, list) -> List[object]:
        self._assure_item_id(item_with_id, list)
        list.append(item_with_id)
        return sorted(list, key=lambda x: x.id)

    def _assure_item_id(self, item_with_id, list):
        if (
            not hasattr(item_with_id, "id")
            or item_with_id.id is None
            or item_with_id.id < 0
        ):
            item_with_id.id = self._get_next_id(list)

    def _get_next_id(self, array_with_ids: List[object]) -> int:
        return (
            sorted(array_with_ids, key=lambda x: x.id, reverse=True)[0].id + 1
            if len(array_with_ids) > 0
            else 0
        )

    def add_alarm_definition_for_powernap(self):

        duration = GeoLocation().now() + timedelta(
            minutes=(1 + self.powernap_duration_in_mins)
        )
        audio_effect = StreamAudioEffect(
            stream_definition=self.audio_streams[0], volume=self.default_volume
        )

        powernap_alarm_def = AlarmDefinition()
        powernap_alarm_def.alarm_name = "Powernap"
        powernap_alarm_def.hour = duration.hour
        powernap_alarm_def.min = duration.minute
        powernap_alarm_def.is_active = True
        powernap_alarm_def.set_future_date(duration.hour, duration.minute)
        powernap_alarm_def.audio_effect = audio_effect
        powernap_alarm_def.visual_effect = None

        self.add_alarm_definition(powernap_alarm_def)

    def get_offline_alarm_effect(
        self, volume: float = default_volume
    ) -> OfflineAlarmEffect:
        full_path = os.path.join(alarms_dir, self.offline_alarm.stream_url)
        return OfflineAlarmEffect(
            stream_definition=AudioStream(
                stream_name="Offline Alarm", stream_url=full_path
            ),
            volume=volume,
        )

    def ensure_valid_config(self):
        for conf_prop in [
            dict(key="alarm_duration_in_mins", value=60),
            dict(
                key="offline_alarm",
                value=AudioStream(
                    stream_name="Offline Alarm", stream_url="Enchantment.ogg"
                ),
            ),
            dict(key="clock_format_string", value="%-H<blinkSegment>%M"),
            dict(key="blink_segment", value=":"),
            dict(key="refresh_timeout_in_secs", value=0.25),
            dict(key="powernap_duration_in_mins", value=18),
            dict(key="default_volume", value=default_volume),
            dict(key="use_analog_clock", value=False),
            dict(key="alarm_preview_hours", value=12),
            dict(key="debug_level", value=0),
        ]:
            if not hasattr(self, conf_prop["key"]):
                logger.debug(
                    "key not found: %s, adding default value: %s",
                    conf_prop["key"],
                    conf_prop["value"],
                )
                setattr(self, conf_prop["key"], conf_prop["value"])

    def serialize(self):
        return jsonpickle.encode(self, indent=2)

    def deserialize(config_file):
        logger.debug("initializing config from file: %s", config_file)
        with open(config_file, "r") as file:
            file_contents = file.read()
            persisted_config: Config = jsonpickle.decode(file_contents)
            persisted_config.ensure_valid_config()
            return persisted_config


class HwButton(Trigger):
    def __init__(
        self, button_id: int, gpio_id: int = None, button_name: str = None, action=None
    ):
        self.button_id = button_id
        self.gpio_id = gpio_id
        self.button_name = button_name
        self.action = action

    def __hash__(self):
        return f"button.{self.button_id}".__hash__()


class TacMode(State):

    def __hash__(self):
        return self.__class__.__name__.__hash__()


class DefaultMode(TacMode):
    pass


class AlarmEditorMode(TacMode):
    alarm_index: int = 0


class AlarmClockStateMachine(StateMachine):
    def __init__(self):
        super().__init__(DefaultMode())
        super().add_definition(
            DefaultMode(),
            StateTransition().add_transition(HwButton(3), AlarmEditorMode()),
        ).add_definition(
            AlarmEditorMode(),
            StateTransition().add_transition(HwButton(3), DefaultMode()),
        )
        pass


class AlarmClockState(TACEventPublisher):

    config: Config
    room_brightness: RoomBrightness = RoomBrightness(1.0)
    show_blink_segment: bool = False
    state_machine: StateMachine = AlarmClockStateMachine()

    @property
    def is_online(self) -> bool:
        return self._is_online

    @is_online.setter
    def is_online(self, value: bool):
        self._is_online = value
        self.publish(property="is_online")

    @property
    def is_daytime(self) -> bool:
        return self._is_daytime

    @is_daytime.setter
    def is_daytime(self, value: bool):
        self._is_daytime = value
        self.publish(property="is_daytime")

    @property
    def mode(self) -> Mode:
        return self._mode

    @mode.setter
    def mode(self, value: Mode):
        self._mode = value
        logger.info("new mode: %s", self.mode.name)
        self.publish(property="mode")

    @property
    def spotify_event(self) -> LibreSpotifyEvent:
        return self._spotify_event

    @spotify_event.setter
    def spotify_event(self, value: LibreSpotifyEvent):
        self._spotify_event = value
        self.publish(property="spotify_event")

    @property
    def active_alarm(self) -> AlarmDefinition:
        return self._active_alarm

    @active_alarm.setter
    def active_alarm(self, value: AlarmDefinition):
        self._active_alarm = value
        self.publish(property="active_alarm")

    def __init__(self, c: Config) -> None:
        super().__init__()
        self.config = c
        self.mode = Mode.Boot
        self.geo_location = GeoLocation()
        self.is_online = True
        self.show_blink_segment = True

    def update_state(
        self, show_blink_segment: bool, brightness: RoomBrightness, is_scrolling: bool
    ):
        if any(
            (
                self.show_blink_segment != show_blink_segment,
                self.room_brightness != brightness,
                is_scrolling,
            )
        ):
            self.show_blink_segment = show_blink_segment
            self.room_brightness = brightness
            self.publish(property="update_state")


class MediaContent(TACEventPublisher, TACEventSubscriber):

    def __init__(self, state: AlarmClockState):
        super().__init__()
        self.state = state


class PlaybackContent(MediaContent):

    @property
    def audio_effect(self) -> AudioEffect:
        return self._audio_effect

    @audio_effect.setter
    def audio_effect(self, value: AudioEffect):

        self._audio_effect = value
        if (
            value is not None
            and value.volume is not None
            and value.volume != self.volume
        ):
            self.volume = value.volume
        self.publish(property="audio_effect")

    @property
    def volume(self) -> float:
        return TACSoundDevice().get_system_volume()

    @volume.setter
    def volume(self, value: float):
        TACSoundDevice().set_system_volume(value)
        self.publish(property="volume")

    @property
    def is_streaming(self) -> str:
        return self._is_streaming

    @is_streaming.setter
    def is_streaming(self, value: bool):
        self._is_streaming = value
        self.publish(property="is_streaming")

    def __init__(self, state: AlarmClockState):
        super().__init__(state)
        self.audio_effect = None
        self.volume = default_volume
        self.is_streaming = False

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if isinstance(observation.subscriber, AlarmClockState):
            self.update_from_state(observation, observation.subscriber)

    def update_from_state(self, observation: TACEvent, state: AlarmClockState):
        if observation.property_name == "mode":
            self.is_streaming = state.mode in [Mode.Alarm, Mode.Music, Mode.Spotify]

        if observation.property_name == "is_online":
            self.wifi_availability_changed(state.is_online)

        if (
            observation.property_name == "active_alarm"
            and state.active_alarm is not None
        ):
            self.audio_effect = state.active_alarm.audio_effect

    def wifi_availability_changed(self, is_online: bool):
        if self.state.mode == Mode.Alarm:
            if not is_online:
                self.audio_effect = self.state.config.get_offline_alarm_effect(
                    self.volume
                )
            else:
                self.audio_effect = self.state.active_alarm.audio_effect

    def increase_volume(self):
        self.volume = min(self.volume + 0.05, 1.0)

    def decrease_volume(self):
        self.volume = max(self.volume - 0.05, 0.0)

    def set_spotify_event(self, spotify_event: LibreSpotifyEvent):

        spotify_audio_effect = (
            self.audio_effect
            if isinstance(self.audio_effect, SpotifyAudioEffect)
            else SpotifyAudioEffect()
        )

        spotify_audio_effect.spotify_event = spotify_event
        if hasattr(spotify_event, "track_id"):
            spotify_audio_effect.track_id = spotify_event.track_id

        if spotify_event.is_playback_started() and self.state.mode != Mode.Spotify:
            self.audio_effect = spotify_audio_effect
            self.state.mode = Mode.Spotify

        if spotify_event.is_playback_stopped() and self.state.mode != Mode.Idle:
            self.state.mode = Mode.Idle

        if spotify_event.is_volume_changed() and self.state.mode == Mode.Spotify:
            self.publish(property="volume")


class DisplayContent(MediaContent):
    _show_volume_meter: bool = False
    next_alarm_job: Job = None
    current_weather: Weather = None
    show_blink_segment: bool
    room_brightness: float
    is_scrolling: bool = False

    def __init__(self, state: AlarmClockState, playback_content: PlaybackContent):
        super().__init__(state)
        self.playback_content = playback_content

    def get_is_online(self) -> bool:
        return self.state.is_online

    def publish(self):
        super().publish(reason="display_changed")

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if isinstance(observation.subscriber, AlarmClockState):
            self.update_from_state(observation, observation.subscriber)
        if isinstance(observation.subscriber, PlaybackContent):
            self.update_from_playback_content(observation, observation.subscriber)

    def update_from_playback_content(
        self, observation: TACEvent, playback_content: PlaybackContent
    ):
        pass

    def update_from_state(self, observation: TACEvent, state: AlarmClockState):
        if observation.property_name == "update_state":
            self.show_blink_segment = state.show_blink_segment
            self.room_brightness = state.room_brightness
            if not observation.during_registration:
                self.publish()

    def hide_volume_meter(self):
        self.show_volume_meter = False

    @property
    def show_volume_meter(self) -> bool:
        return self._show_volume_meter

    @show_volume_meter.setter
    def show_volume_meter(self, value: bool):
        logger.info("volume bar shown: %s", value)
        self._show_volume_meter = value
        self.publish()

    def get_timedelta_to_alarm(self) -> timedelta:
        if self.next_alarm_job is None:
            return timedelta.max
        return get_timedelta_to_alarm(self.next_alarm_job)

    def get_next_alarm(self) -> datetime:
        return (
            None if self.next_alarm_job is None else self.next_alarm_job.next_run_time
        )

    def current_playback_title(self):
        return (
            self.playback_content.audio_effect.title()
            if True
            and self.playback_content.is_streaming
            and self.playback_content.audio_effect is not None
            else None
        )

    def current_volume(self) -> float:
        return self.playback_content.volume
