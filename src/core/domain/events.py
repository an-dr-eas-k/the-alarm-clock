from __future__ import annotations

from dataclasses import dataclass
import json

from core.infrastructure.event_bus import BaseEvent

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.model import (
        Mode,
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
class AlarmTriggeredEvent(BaseEvent):
    alarm_definition: AlarmDefinition
    use_offline_media: bool = False


@dataclass(frozen=True)
class AlarmStoppedEvent(BaseEvent):
    alarm_definition: AlarmDefinition = None


@dataclass(frozen=True)
class ConfigChangedEvent(BaseEvent):
    config: Config


@dataclass(frozen=True)
class SunEventOccurredEvent(BaseEvent):
    event: SunEvent


class SpotifyStoppedEvent(BaseEvent):
    pass


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


class VolumeChangeRequest(BaseEvent):

    relative: int | None = None
    absolute: int | None = None

    def __init__(self, relative: int = None, absolute: int = None):
        self.relative = relative
        self.absolute = absolute
        if relative is not None and absolute is not None:
            raise ValueError(
                "Only one of relative or absolute volume change can be set."
            )


class PlaybackChangedEvent(VolumeChangeRequest):
    playback_mode: Mode
    audio_stream: AudioStream = None

    def __init__(
        self,
        playback_mode: Mode,
        audio_stream: AudioStream = None,
        relative_volume=None,
        absolute_volume=None,
    ):
        super().__init__(relative_volume, absolute_volume)
        self.playback_mode = playback_mode
        self.audio_stream = audio_stream


@dataclass(frozen=True)
class VolumeChangedEvent(BaseEvent):
    new_volume: int = None


@dataclass(frozen=True)
class ToggleAudioRequest(BaseEvent):
    pass


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
    pass


@dataclass(frozen=True)
class SpeakerErrorEvent(BaseEvent):
    audio_stream: AudioStream = None
