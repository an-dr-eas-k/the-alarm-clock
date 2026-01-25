from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta, date
import datetime
import os
from PIL import Image
from typing import List
from enum import Enum
import logging

import jsonpickle
from utils.extensions import T, Value, respect_ranges

from utils.geolocation import GeoLocation, SunEvent, Weather
from resources.resources import alarms_dir, default_volume
from utils.sound_device import SoundDevice

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.infrastructure.event_bus import EventBus
    from core.domain.mode_coordinator import AlarmClockModeCoordinator

from core.domain.events import (
    AlarmStoppedEvent,
    PlaybackChangedEvent,
    SpotifyStoppedEvent,
    VolumeChangeRequest,
    VolumeChangedEvent,
)


logger = logging.getLogger("tac.core.domain.model")


class SchedulerJobIds(Enum):
    hide_volume_meter = "hide_volume_meter_trigger"
    stop_alarm = "stop_alarm_trigger"
    weather_update_interval = "weather_update_trigger"
    wifi_check = "wifi_check_trigger"
    regular_display_refresh = "regular_display_refresh_trigger"
    memory_usage_logger = "memory_usage_logger_trigger"
    thread_usage_logger = "thread_usage_logger_trigger"
    pre_alarm = "pre_alarm_trigger"


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


class EnvironmentContext:
    """
    Aggregate: Current environmental and network conditions.

    Encapsulates knowledge about the physical and network environment
    the alarm clock is operating in.
    """

    def __init__(self, is_online: bool = False):
        self._geo_location = GeoLocation()
        self._is_online = is_online
        self._current_weather: Weather = None
        self.is_daytime = self.geo_location.last_sun_event() == SunEvent.sunrise

    @property
    def geo_location(self) -> GeoLocation:
        """Geographic location service."""
        return self._geo_location

    @property
    def is_online(self) -> bool:
        """Whether network connectivity is available."""
        return self._is_online

    @is_online.setter
    def is_online(self, value: bool):
        """Update network connectivity status."""
        self._is_online = value

    @property
    def is_daytime(self) -> bool:
        """Whether it's currently daytime (based on sunrise/sunset)."""
        return self._is_daytime

    @is_daytime.setter
    def is_daytime(self, value: bool):
        """Update day/night status."""
        self._is_daytime = value

    @property
    def current_weather(self) -> Weather:
        """Current weather conditions."""
        return self._current_weather

    @current_weather.setter
    def current_weather(self, value: Weather):
        """Update current weather conditions."""
        self._current_weather = value


class VisualEffect:

    next_alarm_info: NextAlarmInfo = None

    def is_active(self) -> bool:
        if not self.next_alarm_info:
            return False
        alarm_in_minutes = self.next_alarm_info.minutes_until_alarm()
        return alarm_in_minutes <= 8

    def get_style(self) -> Style:
        alarm_in_minutes = (
            self.next_alarm_info.minutes_until_alarm() if self.next_alarm_info else 9999
        )
        logger.debug("visual effect active for: %smin", alarm_in_minutes)
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


class SpotifyStream(AudioStream):

    def __init__(self, spotify_event: dict | object = None):
        if spotify_event is None:
            spotify_event = {}

        def safe_get(key):
            val = (
                spotify_event.get(key)
                if isinstance(spotify_event, dict)
                else getattr(spotify_event, key, None)
            )
            if isinstance(val, str) and "\n" in val:
                val = val.split("\n")[0]
            return val

        self.player_event = safe_get("player_event")
        self.track_name = safe_get("name")
        self.track_id = safe_get("track_id")
        self.track_artists = safe_get("artists")
        self.track_album = safe_get("album")
        self.track_album_artists = safe_get("album_artists")
        self.track_covers = safe_get("covers")

        stream_name = "Unknown Spotify Track"
        if self.track_name:
            stream_name = f"Spotify: {self.track_name}"
        if self.track_artists:
            if isinstance(self.track_artists, list):
                stream_name += f" by {', '.join(self.track_artists)}"
            else:
                stream_name += f" by {self.track_artists}"

        super().__init__(
            stream_name=stream_name,
            stream_url="",
        )

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

    def __init__(self, audio_stream: AudioStream = None, volume: float = None):
        super().__init__(volume)
        self.audio_stream = audio_stream

    def __str__(self):
        return f"audio_stream: {self.audio_stream} {super().__str__()}"

    def title(self):
        return self.audio_stream.stream_name


class AlarmRecurrence(Enum):
    """Represents whether an alarm is one-time or recurring."""

    ONETIME = "onetime"
    RECURRING = "recurring"


class AlarmDefinition:
    id: int
    hour: int
    min: int

    @property
    def recurrence(self) -> AlarmRecurrence:
        if self.is_recurring():
            return AlarmRecurrence.RECURRING
        elif self.is_onetime():
            return AlarmRecurrence.ONETIME
        else:
            return None

    @recurrence.setter
    def recurrence(self, value: AlarmRecurrence):
        if value == AlarmRecurrence.RECURRING:
            self.recurring = [Weekday.MONDAY.name]
            self.onetime = None
        elif value == AlarmRecurrence.ONETIME:
            self.recurring = None
            self.onetime = date.today()
        else:
            self.recurring = None
            self.onetime = None

    recurring: List[str]
    onetime: date
    alarm_name: str
    is_active: bool
    visual_effect: VisualEffect
    audio_effect: StreamAudioEffect

    @property
    def audio_effect_volume(self) -> float:
        return self.audio_effect.volume if self.audio_effect else None

    @audio_effect_volume.setter
    def audio_effect_volume(self, value: float):
        if self.audio_effect is None:
            self.audio_effect = StreamAudioEffect()
        self.audio_effect.volume = value

    def get_cron_args(self) -> dict:
        if self.is_recurring():
            return {
                "day_of_week": ",".join(
                    [str(Weekday[wd].value - 1) for wd in self.recurring]
                ),
                "hour": self.hour,
                "minute": self.min,
            }
        elif self.is_onetime():
            return {
                "start_date": self.onetime,
                "end_date": self.onetime + timedelta(days=1),
                "hour": self.hour,
                "minute": self.min,
            }
        return {}

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
        return not self.is_recurring()

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
    pre_alarm_trigger_in_mins: int = 10

    # Public attributes for template access (Tornado templates don't call properties)
    alarm_definitions: List[AlarmDefinition]
    audio_streams: List[AudioStream]

    def __init__(self, event_bus: "EventBus" = None):
        logger.debug("initializing default config")
        self.alarm_definitions = []
        self.audio_streams = []
        self.event_bus = event_bus
        self.ensure_valid_config()
        super().__init__()

    def update_alarm_definition(self, alarm_definition: AlarmDefinition):
        self.remove_alarm_definition(alarm_definition.id)
        self.add_alarm_definition(alarm_definition)

    def get_default_audio_stream(self) -> AudioStream:
        if len(self.audio_streams) > 0:
            return self.audio_streams[0]
        return None

    def get_audio_stream_by_id(self, stream_id: int) -> AudioStream:
        streams = self.audio_streams
        return next((s for s in streams if s.id == stream_id), None)

    def add_alarm_definition(self, value: AlarmDefinition):
        self.alarm_definitions = self._append_item_with_id(
            value, self.alarm_definitions
        )

    def remove_alarm_definition(self, id: int):
        if id is None:
            return
        self.alarm_definitions = [
            alarm_def for alarm_def in self.alarm_definitions if alarm_def.id != id
        ]

    def get_default_alarm_definition(self) -> AlarmDefinition:
        if len(self.alarm_definitions) > 0:
            return self.alarm_definitions[0]
        return None

    def get_alarm_definition_by_id(self, id: int) -> AlarmDefinition:
        return next((alarm for alarm in self.alarm_definitions if alarm.id == id), None)

    def add_audio_stream(self, value: AudioStream):
        self.audio_streams = self._append_item_with_id(value, self.audio_streams)

    def remove_audio_stream(self, id: int):
        self.audio_streams = [
            stream_def for stream_def in self.audio_streams if stream_def.id != id
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
            audio_stream=self.audio_streams[0], volume=self.default_volume
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
            dict(key="pre_alarm_trigger_in_mins", value=10),
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
        # Temporarily remove event_bus before serialization to avoid circular references
        event_bus_backup = self.event_bus
        self.event_bus = None
        try:
            serialized = jsonpickle.encode(self, indent=2)
        finally:
            self.event_bus = event_bus_backup
        return serialized

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
    environment: EnvironmentContext
    mode_coordinator: "AlarmClockModeCoordinator"
    active_alarm_definition: AlarmDefinition = None

    def __init__(self, config: Config, is_online: bool = False) -> None:
        self.config = config
        self.environment = EnvironmentContext(is_online)
        self.mode_coordinator: "AlarmClockModeCoordinator" = None


class MediaContent:

    def __init__(self, alarm_clock_context: AlarmClockContext):
        super().__init__()
        self.alarm_clock_context = alarm_clock_context


class PlaybackContent(MediaContent):

    @property
    def playback_mode(self) -> Mode:
        return self._playback_mode

    @playback_mode.setter
    def playback_mode(self, value: Mode):
        logger.debug("setting playback mode to: %s", value)
        self._playback_mode = value

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
        self._playback_mode: Mode = Mode.Boot

        default_volume = self.alarm_clock_context.config.default_volume
        self.sound_device.set_system_volume(default_volume)
        self.audio_stream = None
        self.event_bus.on(PlaybackChangedEvent)(self._playback_change_request)
        self.event_bus.on(VolumeChangeRequest)(self._volume_change_request)

    def _playback_change_request(self, event: PlaybackChangedEvent):
        wasAlarm = self.playback_mode == Mode.Alarm
        wasSpotify = self.playback_mode == Mode.Spotify

        self.playback_mode = event.playback_mode

        if event.audio_stream is not None:
            self.set_audio_stream(event.audio_stream)

        if event.playback_mode != Mode.Idle:
            self._volume_change_request(event)

        if wasAlarm and self.playback_mode != Mode.Alarm:
            self.event_bus.emit(
                AlarmStoppedEvent(self.alarm_clock_context.active_alarm_definition)
            )

        if wasSpotify and self.playback_mode != Mode.Spotify:
            self.event_bus.emit(SpotifyStoppedEvent())

    def set_audio_stream(self, audio_stream: AudioStream):
        logger.debug("setting audio stream to: %s", audio_stream)
        if not self.audio_stream:
            self.audio_stream = audio_stream
            return

        if (
            isinstance(audio_stream, SpotifyStream)
            and audio_stream.player_event != "track_changed"
        ):
            return

        self.audio_stream = audio_stream

    def _volume_change_request(self, event: VolumeChangeRequest):
        volume_changed = False
        if event.relative is not None:
            if event.relative > 0:
                self._increase_volume()
                volume_changed = True
            elif event.relative < 0:
                self._decrease_volume()
                volume_changed = True

        elif event.absolute is not None:
            self.volume = event.absolute
            volume_changed = True

        if volume_changed:
            self.event_bus.emit(VolumeChangedEvent(new_volume=self.volume))

    def _increase_volume(self):
        self.volume = min(self.volume + 0.05, 1.0)

    def _decrease_volume(self):
        self.volume = max(self.volume - 0.05, 0.0)


class NextAlarmInfo:

    def __init__(
        self,
        next_run_time: datetime = None,
        alarm_definition: "AlarmDefinition" = None,
    ):
        self._next_run_time = next_run_time
        self._alarm_definition = alarm_definition
        if self.visual_effect is not None:
            self.visual_effect.next_alarm_info = self

    @property
    def next_run_time(self) -> datetime:
        return self._next_run_time

    @property
    def alarm_name(self) -> str:
        return self._alarm_definition.alarm_name

    @property
    def visual_effect(self) -> "VisualEffect":
        return self._alarm_definition.visual_effect if self._alarm_definition else None

    @property
    def alarm_definition(self) -> "AlarmDefinition":
        return self._alarm_definition

    def _get_timedelta_to_alarm(self) -> timedelta:
        if self._next_run_time is None:
            return timedelta.max
        return self._calculate_time_delta()

    def _calculate_time_delta(self) -> timedelta:
        from utils.geolocation import GeoLocation

        now = GeoLocation().now()
        return self._next_run_time - now

    def minutes_until_alarm(self) -> int:
        return int(self._get_timedelta_to_alarm().total_seconds() / 60)

    def __str__(self):
        return f"{self.alarm_name} at {self.next_run_time}"
