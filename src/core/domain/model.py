from dataclasses import dataclass
from datetime import time, timedelta
import datetime
import os
from PIL import Image
from typing import List
from apscheduler.job import Job
from enum import Enum
import logging

import jsonpickle
from apscheduler.triggers.cron import CronTrigger
from core.domain.events import (
    AudioStreamChangedEvent,
    SpotifyApiEvent,
    RegularDisplayContentUpdateEvent,
    VolumeChangedEvent,
    AudioEffectChangedEvent,
)
from utils.extensions import T, Value, get_timedelta_to_alarm, respect_ranges

from utils.geolocation import GeoLocation, Weather
from resources.resources import alarms_dir, default_volume
from utils.sound_device import SoundDevice
from utils.state_machine import StateMachine
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.infrastructure.event_bus import EventBus

from datetime import datetime, timedelta

logger = logging.getLogger("tac.domain")


class DisplayContentProvider:

    current_display_image: Image.Image


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


@dataclass
class OfflineStream(AudioStream):

    def __init__(self, local_alarm_file: str):
        super().__init__(
            stream_name="Offline Audio",
            stream_url=os.path.join(alarms_dir, local_alarm_file),
        )


@dataclass
class SpotifyStream(AudioStream):
    track_name: str = "Spotify"
    track_id: str = None

    def __str__(self):
        return f"track_name: {self.track_name}, track_id: {self.track_id}"


class AudioEffect:

    volume: float

    def __init__(self, volume: float = None):
        self.volume = volume

    def __str__(self):
        return f"volume: {self.volume}"

    def title(self):
        return None


class StreamAudioEffect(AudioEffect):
    audio_stream: AudioStream = None

    def __init__(self, stream_definition: AudioStream = None, volume: float = None):
        super().__init__(volume)
        self.audio_stream = stream_definition

    def __str__(self):
        return f"stream_definition: {self.audio_stream} {super().__str__()}"

    def title(self):
        return self.audio_stream.stream_name


class SpotifyAudioEffect(AudioEffect):
    spotify_stream: SpotifyStream = SpotifyStream()

    def __init__(self, volume: float = None):
        AudioEffect.__init__(self, volume)

    def __str__(self):
        return f"spotify_stream: {self.spotify_stream} {super().__str__()}"

    def title(self):
        return self.spotify_stream.track_name


class AlarmDefinition:
    id: int
    hour: int
    min: int
    recurring: List[str]
    onetime: datetime
    alarm_name: str
    is_active: bool
    visual_effect: VisualEffect
    audio_effect: AudioEffect

    def to_cron_trigger(self) -> CronTrigger:
        if self.is_recurring():
            return CronTrigger(
                day_of_week=",".join(
                    [str(Weekday[wd].value - 1) for wd in self.recurring]
                ),
                hour=self.hour,
                minute=self.min,
            )
        elif self.is_onetime():
            return CronTrigger(
                start_date=self.onetime,
                end_date=self.onetime + timedelta(days=1),
                hour=self.hour,
                minute=self.min,
            )

        raise ValueError("AlarmDefinition is neither recurring nor onetime")

    def to_time_string(self) -> str:
        return time(hour=self.hour, minute=self.min).strftime("%H:%M")

    def to_day_string(self) -> str:
        if self.is_recurring():
            return ", ".join(
                [Weekday[wd].name.lower().capitalize()[:2] for wd in self.recurring]
            )
        elif self.is_onetime():
            return self.onetime.strftime("%Y-%m-%d")

        raise ValueError("AlarmDefinition is neither recurring nor onetime")

    def set_future_date(self, hour: int, minute: int):
        now = GeoLocation().now()
        target = now.replace(hour=hour, minute=minute)
        if target < now:
            target = target + timedelta(days=1)
        self.onetime = target.date()
        self.recurring = None

    def is_onetime(self) -> bool:
        return self.onetime is not None and self.recurring is None

    def is_recurring(self) -> bool:
        return (
            self.recurring is not None
            and len(self.recurring) > 0
            and self.onetime is None
        )

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


class Config:

    clock_format_string: str
    blink_segment: str
    local_alarm_file: str
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

    def __init__(self, event_bus: "EventBus" = None):
        logger.debug("initializing default config")
        self._alarm_definitions = []
        self._audio_streams = []
        self.event_bus = event_bus
        self.ensure_valid_config()
        super().__init__()

    def update_alarm_definition(self, alarm_definition: AlarmDefinition):
        self.remove_alarm_definition(alarm_definition.id)
        self.add_alarm_definition(alarm_definition)

    def get_audio_stream_by_id(self, stream_id: int) -> AudioStream:
        streams = self.audio_streams
        return next((s for s in streams if s.id == stream_id), streams[0])

    def add_alarm_definition(self, value: AlarmDefinition):
        self._alarm_definitions = self._append_item_with_id(
            value, self._alarm_definitions
        )

    def remove_alarm_definition(self, id: int):
        if id is None:
            return
        self._alarm_definitions = [
            alarm_def for alarm_def in self._alarm_definitions if alarm_def.id != id
        ]

    def get_alarm_definition(self, id: int) -> AlarmDefinition:
        return next(
            (alarm for alarm in self._alarm_definitions if alarm.id == id), None
        )

    def get_audio_stream(self, id: int) -> AudioStream:
        return next((stream for stream in self._audio_streams if stream.id == id), None)

    def add_audio_stream(self, value: AudioStream):
        self._audio_streams = self._append_item_with_id(value, self._audio_streams)

    def remove_audio_stream(self, id: int):
        self._audio_streams = [
            stream_def for stream_def in self._audio_streams if stream_def.id != id
        ]

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

    def get_offline_stream(self) -> OfflineStream:
        return OfflineStream(self.local_alarm_file)

    def ensure_valid_config(self):
        for conf_prop in [
            dict(key="alarm_duration_in_mins", value=60),
            dict(
                key="local_alarm_file",
                value="Enchantment.ogg",
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

    @staticmethod
    def deserialize(config_file, event_bus: "EventBus" = None):
        logger.debug("initializing config from file: %s", config_file)
        with open(config_file, "r") as file:
            file_contents = file.read()
            persisted_config: Config = jsonpickle.decode(file_contents)
            persisted_config.event_bus = event_bus
            persisted_config.ensure_valid_config()
            return persisted_config


class AlarmClockContext:

    config: Config
    state_machine: StateMachine = None
    room_brightness: RoomBrightness = RoomBrightness(1.0)
    show_blink_segment: bool = False
    is_online: bool
    is_daytime: bool
    playback_mode: Mode

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.playback_mode = Mode.Boot
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
            return True
        return False


class MediaContent:

    def __init__(self, alarm_clock_context: AlarmClockContext):
        super().__init__()
        self.alarm_clock_context = alarm_clock_context


class PlaybackContent(MediaContent):

    audio_stream: AudioStream

    @property
    def volume(self) -> float:
        return self.sound_device.get_system_volume()

    @volume.setter
    def volume(self, value: float):
        self.sound_device.set_system_volume(value)

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        sound_device: SoundDevice,
        event_bus: EventBus,
    ):
        super().__init__(alarm_clock_context)
        self.sound_device = sound_device
        self.event_bus = event_bus

        default_volume = self.alarm_clock_context.config.default_volume
        self.sound_device.set_system_volume(default_volume)
        self.audio_stream = None
        self.event_bus.on(SpotifyApiEvent)(self._set_spotify_api_event)
        self.event_bus.on(AudioEffectChangedEvent)(self._audio_effect_changed)
        self.event_bus.on(AudioStreamChangedEvent)(self._audio_stream_changed)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)

    def _audio_effect_changed(self, event: AudioEffectChangedEvent):
        self.event_bus.emit(
            VolumeChangedEvent(
                event.audio_effect.volume
                or self.alarm_clock_context.config.default_volume
            )
        )
        if isinstance(event.audio_effect, StreamAudioEffect):
            self.event_bus.emit(
                AudioStreamChangedEvent(event.audio_effect.audio_stream)
            )

    def _audio_stream_changed(self, event: AudioStreamChangedEvent):
        self.audio_stream = event.audio_stream

    def _volume_changed(self, event: VolumeChangedEvent):
        if event.volume_delta > 0:
            self.increase_volume()
        elif event.volume_delta < 0:
            self.decrease_volume()

    def increase_volume(self):
        self.volume = min(self.volume + 0.05, 1.0)

    def decrease_volume(self):
        self.volume = max(self.volume - 0.05, 0.0)

    def _set_spotify_api_event(self, spotify_event: SpotifyApiEvent):
        spotify_audio_effect = SpotifyAudioEffect()

        spotify_stream = SpotifyStream()
        if hasattr(spotify_event, "track_id"):
            spotify_stream.track_id = spotify_event.track_id
        spotify_audio_effect.spotify_stream = spotify_stream

        self.audio_stream = spotify_stream

        if (
            spotify_event.is_playback_started()
            and self.alarm_clock_context.playback_mode != Mode.Spotify
        ):
            self.alarm_clock_context.playback_mode = Mode.Spotify

        if (
            spotify_event.is_playback_stopped()
            and self.alarm_clock_context.playback_mode != Mode.Idle
        ):
            self.alarm_clock_context.playback_mode = Mode.Idle

        if (
            spotify_event.is_volume_changed()
            and self.alarm_clock_context.playback_mode == Mode.Spotify
        ):
            self.event_bus.emit(VolumeChangedEvent(0))


class DisplayContent(MediaContent):
    show_volume_meter: bool = False
    next_alarm_job: Job = None
    current_weather: Weather = None
    show_blink_segment: bool
    room_brightness: float
    is_scrolling: bool = False

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        playback_content: PlaybackContent,
        event_bus: "EventBus" = None,
    ):
        super().__init__(alarm_clock_context)
        self.playback_content = playback_content
        self.event_bus = event_bus
        self.event_bus.on(RegularDisplayContentUpdateEvent)(self._regular_update)
        self.event_bus.on(AudioEffectChangedEvent)(self._audio_effect_changed)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)

    def _audio_effect_changed(self, event: AudioEffectChangedEvent):
        if event.audio_effect is None:
            self.hide_volume_meter()

    def _volume_changed(self, _: VolumeChangedEvent):
        self.show_volume_meter = True

    def get_is_online(self) -> bool:
        return self.alarm_clock_context.is_online

    def _regular_update(self, event: RegularDisplayContentUpdateEvent):
        self.show_blink_segment = event.show_blink_segment
        self.room_brightness = event.room_brightness.value
        self.is_scrolling = event.is_scrolling

    def hide_volume_meter(self):
        self.show_volume_meter = False

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
            self.playback_content.audio_stream.title()
            if True
            and super().alarm_clock_context != Mode.Idle
            and self.playback_content.audio_stream is not None
            else None
        )

    def current_volume(self) -> float:
        return self.playback_content.volume
