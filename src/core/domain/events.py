from __future__ import annotations

from dataclasses import dataclass
import json

from core.infrastructure.event_bus import BaseEvent

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.model import (
        AudioEffect,
        AudioStream,
        RoomBrightness,
        AlarmDefinition,
        Config,
        RoomBrightness,
    )
    from utils.geolocation import SunEvent


@dataclass(frozen=True)
class WifiStatusChangedEvent(BaseEvent):
    is_online: bool


@dataclass(frozen=True)
class AlarmEvent(BaseEvent):
    alarm_definition: AlarmDefinition


@dataclass(frozen=True)
class ConfigChangedEvent(BaseEvent):
    config: Config


@dataclass(frozen=True)
class SunEventOccurredEvent(BaseEvent):
    event: SunEvent


class SpotifyApiEvent(BaseEvent):

    name: str
    player_event: str = None
    track_id: str
    old_track_id: str
    duration_ms: str
    position_ms: str
    volume: str
    sink_status: str

    def __init__(self, dict: dict):
        for key, value in dict.items():
            setattr(self, key, value)

    def is_playback_started(self) -> bool:
        return self.player_event in [
            "session_connected",
            "playing",
            "started",
            "changed",
        ]

    def is_playback_stopped(self) -> bool:
        return self.player_event in ["session_disconnected", "stopped", "paused"]

    def is_volume_changed(self) -> bool:
        return self.player_event in ["volume_changed"]

    def __str__(self):
        return json.dumps(self.__dict__)


@dataclass(frozen=True)
class VolumeChangedEvent(BaseEvent):
    volume_delta: int


@dataclass(frozen=True)
class AudioStreamChangedEvent(BaseEvent):
    audio_stream: AudioStream
    use_alternative_player: bool = False


@dataclass(frozen=True)
class ToggleAudioEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class AudioEffectChangedEvent(BaseEvent):
    audio_effect: AudioEffect


@dataclass(frozen=True)
class AlarmPropertySelectedEvent(BaseEvent):
    alarm_property_index_delta: int


@dataclass(frozen=True)
class StartAlarmPropertyEditEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class AlarmPropertyValueSelectedEvent(BaseEvent):
    alarm_property_value_index_delta: int


@dataclass(frozen=True)
class ForcedDisplayUpdateEvent(BaseEvent):
    suppress_logging: bool = False


@dataclass(frozen=True)
class RegularDisplayContentUpdateEvent(BaseEvent):
    show_blink_segment: bool
    room_brightness: RoomBrightness
    suppress_logging: bool = True


@dataclass(frozen=True)
class SpeakerErrorEvent(BaseEvent):
    offline_stream_failed: bool
