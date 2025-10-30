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
    AlarmEvent,
    LibreSpotifyApiEvent,
    RegularDisplayContentUpdateEvent,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
    AudioEffectEvent,
)
from utils.extensions import T, Value, get_timedelta_to_alarm, respect_ranges

from utils.events import TACEventPublisher, TACEvent, TACEventSubscriber
from utils.geolocation import GeoLocation, Weather
from resources.resources import alarms_dir, default_volume
from utils.singleton import singleton
from utils.sound_device import SoundDevice
from utils.state_machine import StateMachine, Trigger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.infrastructure.event_bus import EventBus

from datetime import datetime, timedelta

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


class AudioEffect:

    volume: float

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
class OfflineAudioEffect(StreamAudioEffect):

    def title(self):
        return "Offline Audio"


class SpotifyAudioEffect(AudioEffect):
    spotify_event: LibreSpotifyApiEvent = None
    track_name: str = "Spotify"
    track_id: str = None

    def __init__(self, volume: float = None):
        AudioEffect.__init__(self, volume)

    def __str__(self):
        return f"track_id: {self.track_id}, spotify_event: {self.spotify_event} {super().__str__()}"

    def title(self):
        return self.track_name


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

    def add_alarm_definition(self, value: AlarmDefinition):
        self._alarm_definitions = self._append_item_with_id(
            value, self._alarm_definitions
        )
        self.publish(property="alarm_definitions")

    def remove_alarm_definition(self, id: int):
        if id is None:
            return
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

    def get_offline_audio_effect(
        self, volume: float = default_volume
    ) -> OfflineAudioEffect:
        full_path = os.path.join(alarms_dir, self.offline_alarm.stream_url)
        return OfflineAudioEffect(
            stream_definition=AudioStream(
                stream_name="Offline Audio", stream_url=full_path
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

    @staticmethod
    def deserialize(config_file, event_bus: "EventBus" = None):
        logger.debug("initializing config from file: %s", config_file)
        with open(config_file, "r") as file:
            file_contents = file.read()
            persisted_config: Config = jsonpickle.decode(file_contents)
            persisted_config.event_bus = event_bus
            persisted_config.ensure_valid_config()
            return persisted_config


class HwButton(Trigger):
    def __init__(self, button_id: str):
        self.button_id = button_id

    def __hash__(self):
        return f"button.{self.button_id}".__hash__()

    def __str__(self):
        return f"{super().__str__()} {self.button_id}"


class AlarmClockContext(TACEventPublisher):

    config: Config
    state_machine: StateMachine = None
    room_brightness: RoomBrightness = RoomBrightness(1.0)
    show_blink_segment: bool = False
    is_online: bool
    is_daytime: bool
    active_alarm: AlarmDefinition

    @property
    def playback_mode(self) -> Mode:
        return self._mode

    @playback_mode.setter
    def playback_mode(self, value: Mode):
        self._mode = value
        logger.info("new mode: %s", self.playback_mode.name)
        self.publish(property="mode")

    def __init__(self, config: Config, event_bus: EventBus) -> None:
        super().__init__()
        self.config = config
        self.playback_mode = Mode.Boot
        self.geo_location = GeoLocation()
        self.is_online = True
        self.show_blink_segment = True
        self.event_bus = event_bus

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


class MediaContent(TACEventPublisher, TACEventSubscriber):

    def __init__(self, alarm_clock_context: AlarmClockContext):
        super().__init__()
        self.alarm_clock_context = alarm_clock_context


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
        self.audio_effect = None
        self.sound_device.set_system_volume(default_volume)
        self.event_bus = event_bus
        self.event_bus.on(LibreSpotifyApiEvent)(self._set_spotify_event)
        self.event_bus.on(WifiStatusChangedEvent)(self._wifi_status_changed)
        self.event_bus.on(AlarmEvent)(self._alarm_event)

    def _alarm_event(self, event: AlarmEvent):
        if event.alarm_definition is not None:
            self.audio_effect = event.alarm_definition.audio_effect

    def _wifi_status_changed(self, event: WifiStatusChangedEvent):
        if self.alarm_clock_context.playback_mode == Mode.Alarm:
            if not event.is_online:
                self.audio_effect = (
                    self.alarm_clock_context.config.get_offline_alarm_effect(
                        self.volume
                    )
                )
            else:
                self.audio_effect = self.alarm_clock_context.active_alarm.audio_effect

    def increase_volume(self):
        self.volume = min(self.volume + 0.05, 1.0)

    def decrease_volume(self):
        self.volume = max(self.volume - 0.05, 0.0)

    def _set_spotify_event(self, spotify_event: LibreSpotifyApiEvent):
        spotify_audio_effect = (
            self.audio_effect
            if isinstance(self.audio_effect, SpotifyAudioEffect)
            else SpotifyAudioEffect()
        )

        spotify_audio_effect.spotify_event = spotify_event
        if hasattr(spotify_event, "track_id"):
            spotify_audio_effect.track_id = spotify_event.track_id

        if (
            spotify_event.is_playback_started()
            and self.alarm_clock_context.playback_mode != Mode.Spotify
        ):
            self.audio_effect = spotify_audio_effect
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
    _show_volume_meter: bool = False
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
        self.event_bus.on(AudioEffectEvent)(
            lambda e: self.hide_volume_meter() if e.audio_effect is None else None,
        )

    def get_is_online(self) -> bool:
        return self.alarm_clock_context.is_online

    def _regular_update(self, event: RegularDisplayContentUpdateEvent):
        self.show_blink_segment = event.show_blink_segment
        self.room_brightness = event.room_brightness.value
        self.is_scrolling = event.is_scrolling

    def hide_volume_meter(self):
        self.show_volume_meter = False

    @property
    def show_volume_meter(self) -> bool:
        return self._show_volume_meter

    @show_volume_meter.setter
    def show_volume_meter(self, value: bool):
        logger.info("volume bar shown: %s", value)
        self._show_volume_meter = value

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
            if True and self.playback_content.audio_effect is not None
            else None
        )

    def current_volume(self) -> float:
        return self.playback_content.volume
