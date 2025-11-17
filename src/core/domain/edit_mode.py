from enum import Enum


class EditorAction(Enum):
    COMMIT = "commit"
    CANCEL = "cancel"


class AlarmProperty(Enum):
    IS_ACTIVE = "is_active"
    HOUR = "hour"
    MIN = "min"
    DAY_TYPE = "day_type"
    ONETIME = "onetime"
    RECURRING = "recurring"
    AUDIO_EFFECT = "audio_effect"
