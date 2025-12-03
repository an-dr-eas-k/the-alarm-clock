from datetime import timedelta
import datetime
from typing import Dict, List
import logging

from core.domain.edit_mode import AlarmProperty, AlarmRecurrence
from core.domain.model import AlarmDefinition, Config, StreamAudioEffect, Weekday

from datetime import datetime, timedelta

logger = logging.getLogger("tac.core.interface.display.editor.alarm_definition_editor")


class EditableProperty:

    def __init__(self, name: AlarmProperty, value_list: List = None):
        self.name = name
        self.value_list = value_list


class AlarmDefinitionProperties:

    recurrence: AlarmRecurrence = AlarmRecurrence.ONETIME
    _editable_properties: Dict[AlarmProperty, EditableProperty]

    def __init__(self):

        self._editable_properties = {
            AlarmProperty.HOUR: EditableProperty(AlarmProperty.HOUR, list(range(24))),
            AlarmProperty.MIN: EditableProperty(AlarmProperty.MIN, list(range(60))),
            AlarmProperty.RECURRENCE: EditableProperty(
                AlarmProperty.RECURRENCE,
                [AlarmRecurrence.ONETIME, AlarmRecurrence.RECURRING],
            ),
            AlarmProperty.ONETIME: EditableProperty(
                AlarmProperty.ONETIME,
                [None]
                + [
                    (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(30)
                ],
            ),
            AlarmProperty.RECURRING: EditableProperty(
                AlarmProperty.RECURRING,
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
            ),
            AlarmProperty.AUDIO_EFFECT: EditableProperty(
                AlarmProperty.AUDIO_EFFECT, None
            ),
            AlarmProperty.IS_ACTIVE: EditableProperty(
                AlarmProperty.IS_ACTIVE, [True, False]
            ),
        }

    def get_editable_property(self, property: AlarmProperty) -> EditableProperty:
        return self._editable_properties[property]

    def get_properties_to_edit(
        self, alarm_definition: AlarmDefinition
    ) -> List[AlarmProperty]:
        pes = []
        pes.append(AlarmProperty.IS_ACTIVE)
        pes.append(AlarmProperty.HOUR)
        pes.append(AlarmProperty.MIN)
        pes.append(AlarmProperty.RECURRENCE)

        if alarm_definition.recurrence == AlarmRecurrence.ONETIME:
            pes.append(AlarmProperty.ONETIME)
        else:
            pes.append(AlarmProperty.RECURRING)

        pes.append(AlarmProperty.AUDIO_EFFECT)
        return pes

    def update_value_lists(self, config: Config, volume: float):
        self._editable_properties[AlarmProperty.AUDIO_EFFECT].value_list = [
            StreamAudioEffect(audio_stream=stream, volume=volume)
            for stream in config.audio_streams
        ]
