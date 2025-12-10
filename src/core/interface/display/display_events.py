from dataclasses import dataclass

from core.infrastructure.event_bus import BaseEvent


@dataclass(frozen=True)
class DisplayPlaybackUpdatedEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class DisplayVolumeUpdatedEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class DisplayNextAlarmUpdatedEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class DisplayWeatherUpdatedEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class DisplayBrightnessUpdatedEvent(BaseEvent):
    pass
