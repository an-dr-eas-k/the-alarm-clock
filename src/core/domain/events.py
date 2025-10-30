from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Optional, Any

from core.domain.model import (
    AudioEffect,
    RoomBrightness,
    AlarmDefinition,
    Config,
    Config,
    RoomBrightness,
)
from core.infrastructure.event_bus import BaseEvent
from utils.geolocation import SunEvent


@dataclass(frozen=True)
class DomainEvent(BaseEvent):
    pass


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


class LibreSpotifyApiEvent(BaseEvent):

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
class VolumeChangedEvent(DomainEvent):
    volume_delta: int


@dataclass(frozen=True)
class ToggleAudioEvent(DomainEvent):
    pass


@dataclass(frozen=True)
class AudioEffectEvent(DomainEvent):
    audio_effect: AudioEffect


@dataclass(frozen=True)
class ModeChanged(DomainEvent):
    previous_mode: str
    new_mode: str


@dataclass(frozen=True)
class AlarmSelectedEvent(DomainEvent):
    alarm_index_delta: int


@dataclass(frozen=True)
class AlarmPropertySelectedEvent(DomainEvent):
    alarm_property_index_delta: int


@dataclass(frozen=True)
class StartAlarmPropertyEditEvent(DomainEvent):
    pass


@dataclass(frozen=True)
class AlarmPropertyValueSelectedEvent(DomainEvent):
    alarm_property_value_index_delta: int


@dataclass(frozen=True)
class RegularDisplayContentUpdateEvent(DomainEvent):
    show_blink_segment: bool
    room_brightness: RoomBrightness
    is_scrolling: bool


@dataclass(frozen=True)
class AlarmEditStarted(DomainEvent):
    alarm_index: int


@dataclass(frozen=True)
class AlarmEditEnded(DomainEvent):
    alarm_index: Optional[int]
    committed: bool


@dataclass(frozen=True)
class AlarmPropertyValueChanged(DomainEvent):
    alarm_index: int
    property_name: str
    new_value: Any


@dataclass(frozen=True)
class AlarmCommitted(DomainEvent):
    alarm_index: int
    alarm_id: Optional[str]


@dataclass(frozen=True)
class AlarmCreated(DomainEvent):
    alarm_index: int
    alarm_id: Optional[str]


@dataclass(frozen=True)
class AlarmEditCancelled(DomainEvent):
    alarm_index: Optional[int]


@dataclass(frozen=True)
class ConfigPropertyChanged(DomainEvent):
    """Domain event: A configuration property has been changed."""

    property_name: str = None
    old_value: Any = None
    new_value: Any = None


# Trigger abstractions (domain level, independent from hardware buttons)
class DomainTrigger:
    """Marker for domain-level triggers decoupled from hardware events."""

    def __repr__(self):
        return self.__class__.__name__


# Navigation triggers
class EnterDefault(DomainTrigger):
    pass


class EnterAlarmView(DomainTrigger):
    pass


class StartAlarmEdit(DomainTrigger):
    pass


class FocusNextAlarm(DomainTrigger):
    pass


class FocusPreviousAlarm(DomainTrigger):
    pass


class FocusNextProperty(DomainTrigger):
    pass


class FocusPreviousProperty(DomainTrigger):
    pass


class FocusNextValue(DomainTrigger):
    pass


class FocusPreviousValue(DomainTrigger):
    pass


class CommitAlarmEdit(DomainTrigger):
    pass


class CancelAlarmEdit(DomainTrigger):
    pass


# Composite trigger when property editing starts
class StartPropertyEdit(DomainTrigger):
    pass
