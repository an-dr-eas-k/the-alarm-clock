from datetime import timedelta
import datetime
from typing import List
import logging

from core.domain.model import AlarmDefinition, Config, StreamAudioEffect, Weekday

from datetime import datetime, timedelta

logger = logging.getLogger("tac.domain")


class EditableProperty:

    def __init__(self, name: str, value_list: List = None):
        self.name = name
        self.value_list = value_list


class AlarmDefinitionToEdit(AlarmDefinition):

    day_type: str = "onetime"

    _hour: EditableProperty = EditableProperty("hour", list(range(24)))
    _min: EditableProperty = EditableProperty("min", list(range(60)))
    _day_type: EditableProperty = EditableProperty("day_type", ["onetime", "recurring"])
    _onetime: EditableProperty = EditableProperty(
        "onetime",
        [None]
        + [
            (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)
        ],
    )
    _recurring: EditableProperty = EditableProperty(
        "recurring",
        [
            [Weekday.MONDAY.name],
            [Weekday.TUESDAY.name],
            [Weekday.WEDNESDAY.name],
            [Weekday.THURSDAY.name],
            [Weekday.FRIDAY.name],
            [Weekday.SATURDAY.name],
            [Weekday.SUNDAY.name],
            [Weekday.SATURDAY.name, Weekday.SUNDAY.name],
            [
                Weekday.MONDAY.name,
                Weekday.TUESDAY.name,
                Weekday.WEDNESDAY.name,
                Weekday.THURSDAY.name,
                Weekday.FRIDAY.name,
            ],
            [
                Weekday.MONDAY.name,
                Weekday.TUESDAY.name,
                Weekday.WEDNESDAY.name,
                Weekday.THURSDAY.name,
                Weekday.FRIDAY.name,
                Weekday.SATURDAY.name,
                Weekday.SUNDAY.name,
            ],
        ],
    )
    _audio_effect: EditableProperty = EditableProperty("audio_effect", None)
    _is_active: EditableProperty = EditableProperty("is_active", [True, False])

    def __init__(self, alarm_definition: AlarmDefinition = None):
        if alarm_definition is None:
            return
        self.id = alarm_definition.id
        self.alarm_name = alarm_definition.alarm_name
        self.is_active = alarm_definition.is_active
        self.hour = alarm_definition.hour
        self.min = alarm_definition.min
        self.onetime = alarm_definition.onetime
        self.recurring = alarm_definition.recurring
        self.day_type = "onetime" if alarm_definition.is_onetime() else "recurring"
        self.visual_effect = alarm_definition.visual_effect
        self.audio_effect = alarm_definition.audio_effect

    def get_editable_property(self, property_name: str) -> EditableProperty:
        ep: EditableProperty = getattr(self, "_" + property_name)
        return ep

    def get_properties_to_edit(self) -> List[str]:
        pes = ["hour", "min"]
        if not super().is_onetime() and not super().is_recurring():
            pes.append("dayType")

        if self.day_type == "onetime":
            pes.append("onetime")
        else:
            pes.append("recurring")

        pes.append("audio_effect")
        pes.append("is_active")
        pes.append("update")
        pes.append("cancel")
        return pes

    def update_value_lists(self, config: Config, volume: float):
        self._audio_effect.value_list = [
            StreamAudioEffect(stream_definition=stream, volume=volume)
            for stream in config.audio_streams
        ]
