import dataclasses
from dataclasses import dataclass
from typing import Optional, Any


# Domain Event base
@dataclass(frozen=True)
class DomainEvent:
    """Base class for domain events. Immutable value object representing a fact that occurred."""

    pass


# Mode / Navigation Events
@dataclass(frozen=True)
class ModeChanged(DomainEvent):
    previous_mode: str
    new_mode: str


@dataclass(frozen=True)
class AlarmSelected(DomainEvent):
    alarm_index: int
    is_new: bool


@dataclass(frozen=True)
class AlarmEditStarted(DomainEvent):
    alarm_index: int


@dataclass(frozen=True)
class AlarmEditEnded(DomainEvent):
    alarm_index: Optional[int]
    committed: bool


@dataclass(frozen=True)
class AlarmPropertyFocused(DomainEvent):
    alarm_index: int
    property_name: str


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
class AlarmEditCancelled(DomainEvent):
    alarm_index: Optional[int]


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
