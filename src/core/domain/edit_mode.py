from enum import Enum


class EditorAction(Enum):
    COMMIT = "commit"
    CANCEL = "cancel"


class AlarmRecurrence(Enum):
    """Represents whether an alarm is one-time or recurring."""

    ONETIME = "onetime"
    RECURRING = "recurring"


class AlarmProperty(Enum):
    IS_ACTIVE = "is_active"
    HOUR = "hour"
    MIN = "min"
    RECURRENCE = "recurrence"
    ONETIME = "onetime"
    RECURRING = "recurring"
    AUDIO_EFFECT = "audio_effect"
