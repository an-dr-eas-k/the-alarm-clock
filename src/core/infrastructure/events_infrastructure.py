from dataclasses import dataclass
from core.infrastructure.event_bus import BaseEvent

from enum import Enum, auto

from utils.state_machine import Trigger


class DeviceName(Enum):
    MODE_BUTTON = "mode_button"
    INVOKE_BUTTON = "invoke_button"
    ROTARY_ENCODER = "rotary_encoder"

    def __str__(self) -> str:
        return self.value


class ButtonDirection(Enum):
    DOWN = "down"
    UP = "up"

    def __str__(self) -> str:
        return self.name.lower()


class RotaryDirection(Enum):
    CLOCKWISE = "clockwise"
    COUNTERCLOCKWISE = "counterclockwise"

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class HwEvent(BaseEvent, Trigger):
    device_name: DeviceName


@dataclass(frozen=True)
class HwButtonEvent(HwEvent):
    direction: ButtonDirection = ButtonDirection.DOWN

    def __str__(self):
        return f"{self.__class__.__name__}.{self.device_name}.{self.direction}"


@dataclass(frozen=True)
class HwRotaryEvent(HwEvent):
    direction: RotaryDirection

    def __str__(self):
        return f"{self.__class__.__name__}.{self.device_name}.{self.direction}"
