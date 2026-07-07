from copy import deepcopy
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Union
import logging

from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    AlarmRecurrence,
    Config,
    StreamAudioEffect,
    VisualEffect,
    Weekday,
)
from utils.geolocation import GeoLocation

logger = logging.getLogger("tac.core.interface.display.editor.alarm_definition_editor")


class EditorAction(Enum):
    COMMIT = "commit"
    CANCEL = "cancel"


class AlarmProperty(Enum):
    IS_ACTIVE = "is_active"
    HOUR = "hour"
    MIN = "min"
    RECURRENCE = "recurrence"
    ONETIME = "onetime"
    RECURRING = "recurring"
    AUDIO_EFFECT = "audio_effect"
    AUDIO_EFFECT_VOLUME = "audio_effect_volume"
    FADE_IN = "fadein_in_secs"
    VISUAL_EFFECT = "visual_effect"


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
                [None] + [(date.today() + timedelta(days=i)) for i in range(30)],
            ),
            AlarmProperty.RECURRING: EditableProperty(
                AlarmProperty.RECURRING,
                None,
            ),
            AlarmProperty.AUDIO_EFFECT: EditableProperty(
                AlarmProperty.AUDIO_EFFECT, None
            ),
            AlarmProperty.AUDIO_EFFECT_VOLUME: EditableProperty(
                AlarmProperty.AUDIO_EFFECT_VOLUME, [i * 0.05 for i in range(21)]
            ),
            AlarmProperty.FADE_IN: EditableProperty(
                AlarmProperty.FADE_IN, list(range(0, 310, 10))
            ),
            AlarmProperty.VISUAL_EFFECT: EditableProperty(
                AlarmProperty.VISUAL_EFFECT, [VisualEffect(), None]
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
        pes.append(AlarmProperty.AUDIO_EFFECT_VOLUME)
        pes.append(AlarmProperty.FADE_IN)

        pes.append(AlarmProperty.VISUAL_EFFECT)
        return pes

    def update_value_lists(self, config: Config, volume: float):
        self._editable_properties[AlarmProperty.AUDIO_EFFECT].value_list = [
            StreamAudioEffect(audio_stream=stream, volume=volume)
            for stream in config.audio_streams
        ]


class DayPickerSession:
    """Interactive per-day selector: 7 weekday toggles + OK."""

    DAYS = [
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
        Weekday.SATURDAY,
        Weekday.SUNDAY,
    ]
    OK_INDEX = 7

    def __init__(self, current_days: List[str]):
        self._active_days: set = set(current_days) if current_days else set()
        self._cursor: int = 0

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def active_days(self) -> set:
        return self._active_days

    def is_on_ok(self) -> bool:
        return self._cursor == self.OK_INDEX

    def navigate(self, direction: int):
        self._cursor = (self._cursor + direction) % (len(self.DAYS) + 1)

    def toggle_current(self):
        if self._cursor < len(self.DAYS):
            day_name = self.DAYS[self._cursor].name
            if day_name in self._active_days:
                self._active_days.discard(day_name)
            else:
                self._active_days.add(day_name)

    def get_selected_days(self) -> List[str]:
        """Return selected days in canonical weekday order."""
        return [d.name for d in self.DAYS if d.name in self._active_days]


class AlarmEditingSession:

    def __init__(self, alarm: AlarmDefinition, config: "Config"):
        self._original_alarm = alarm
        self._draft_alarm = self._create_draft(alarm)
        self._current_property_index = 0
        self._property_editor = AlarmDefinitionProperties()
        self._property_editor.update_value_lists(
            config, self._draft_alarm.audio_effect.volume
        )
        self._properties = self._build_property_list()
        self._day_picker_session: Optional[DayPickerSession] = None

    def _create_draft(self, alarm: AlarmDefinition) -> AlarmDefinition:
        return deepcopy(alarm)

    def _build_property_list(self) -> List[Union[AlarmProperty, EditorAction]]:
        return self._property_editor.get_properties_to_edit(self._draft_alarm) + [
            EditorAction.COMMIT,
            EditorAction.CANCEL,
        ]

    @property
    def day_picker_session(self) -> Optional["DayPickerSession"]:
        return self._day_picker_session

    def start_day_picker(self):
        current_days = self._draft_alarm.recurring or []
        self._day_picker_session = DayPickerSession(current_days)
        logger.debug("Started day picker session")

    def confirm_day_picker(self):
        if self._day_picker_session:
            self._draft_alarm.recurring = self._day_picker_session.get_selected_days()
            self._day_picker_session = None
            logger.debug(f"Confirmed day picker: {self._draft_alarm.recurring}")

    def cancel_day_picker(self):
        self._day_picker_session = None
        logger.debug("Cancelled day picker session")

    @property
    def draft_alarm(self) -> AlarmDefinition:
        return self._draft_alarm

    @property
    def current_property(self) -> Union[AlarmProperty, EditorAction]:
        return self._properties[self._current_property_index]

    @property
    def is_on_action(self) -> bool:
        return isinstance(self.current_property, EditorAction)

    def navigate_property(self, direction: int):
        self._properties = self._build_property_list()
        self._current_property_index = (self._current_property_index + direction) % len(
            self._properties
        )
        logger.debug(f"Navigated to property: {self.current_property}")

    def get_property_values(self) -> List:
        if self.is_on_action:
            return []
        return self._property_editor.get_editable_property(
            self.current_property
        ).value_list

    def get_current_value(self):
        if self.is_on_action:
            return None
        return getattr(self._draft_alarm, self.current_property.value)

    def change_property_value(self, value):
        if self.is_on_action:
            return

        old_value = self.get_current_value()
        setattr(self._draft_alarm, self.current_property.value, value)
        logger.debug(f"Changed {self.current_property} from {old_value} to {value}")

        if self.current_property == AlarmProperty.RECURRENCE:
            self._properties = self._build_property_list()

    def navigate_value(self, direction: int):
        if self.is_on_action:
            return

        values = self.get_property_values()
        if not values:
            return

        current_value = self.get_current_value()
        try:
            current_index = values.index(current_value)
        except ValueError:
            current_index = 0

        next_index = (current_index + direction) % len(values)
        self.change_property_value(values[next_index])

    def should_enter_value_edit_mode(self) -> bool:
        if self.is_on_action:
            return False
        values = self.get_property_values()
        return len(values) != 2

    def commit(self) -> AlarmDefinition:
        logger.info(f"Committing alarm changes: {self._draft_alarm.alarm_name}")
        return self._draft_alarm

    def cancel(self):
        logger.info(f"Cancelling alarm changes")


class AlarmEditingService:

    def __init__(self, alarm_clock_context: "AlarmClockContext"):
        self.alarm_clock_context = alarm_clock_context
        self._alarm_index = 0
        self._editing_session: Optional[AlarmEditingSession] = None

    @property
    def current_alarm_index(self) -> int:
        return self._alarm_index

    @property
    def current_alarm(self) -> AlarmDefinition:
        return self._get_alarm_at_index(self._alarm_index)

    @property
    def editing_session(self) -> Optional[AlarmEditingSession]:
        return self._editing_session

    @property
    def property_to_edit(self) -> Optional[Union[AlarmProperty, EditorAction]]:
        return self._editing_session.current_property if self._editing_session else None

    @property
    def alarm_definition_in_editing(self) -> Optional[AlarmDefinition]:
        return (
            self._editing_session.draft_alarm
            if self._editing_session
            else self.current_alarm
        )

    def start_editing(self):
        alarm = self.current_alarm
        self._editing_session = AlarmEditingSession(
            alarm, self.alarm_clock_context.config
        )
        logger.debug(f"Started editing session for: {alarm.alarm_name}")

    def continue_editing(self):
        pass

    def start_property_value_editing(self) -> bool:
        if not self._editing_session:
            return False

        values = self._editing_session.get_property_values()
        if len(values) == 2:
            self._editing_session.navigate_value(1)
            return False

        return self._editing_session.should_enter_value_edit_mode()

    def _get_alarm_at_index(self, index: int) -> AlarmDefinition:
        alarms = self.alarm_clock_context.config.alarm_definitions

        if index < len(alarms):
            return alarms[index]

        return self._create_new_alarm()

    def _create_new_alarm(self) -> AlarmDefinition:
        now = GeoLocation().now()
        alarm = AlarmDefinition()
        alarm.id = None
        alarm.alarm_name = "New Alarm"
        alarm.hour = now.hour
        alarm.min = now.minute
        alarm.is_active = True
        alarm.recurring = None
        alarm.onetime = now.date()

        if self.alarm_clock_context.config.audio_streams:
            alarm.audio_effect = StreamAudioEffect(
                audio_stream=self.alarm_clock_context.config.get_default_audio_stream(),
                volume=self.alarm_clock_context.config.default_volume,
            )
        alarm.visual_effect = VisualEffect()

        logger.debug(f"Created new alarm template")
        return alarm

    def navigate_alarms(self, direction: int):
        max_index = len(self.alarm_clock_context.config.alarm_definitions)
        self._alarm_index = (self._alarm_index + direction) % (max_index + 1)
        logger.debug(f"Navigated to alarm index: {self._alarm_index}")

    def navigate_properties(self, direction: int):
        if self._editing_session:
            self._editing_session.navigate_property(direction)

    def navigate_value_list(self, direction: int):
        if self._editing_session:
            self._editing_session.navigate_value(direction)

    def is_in_edit_mode(self, properties: List[AlarmProperty]) -> bool:
        return self.property_to_edit in properties if self.property_to_edit else False

    def commit_changes(self) -> AlarmDefinition:
        if not self._editing_session:
            return None

        alarm = self._editing_session.commit()

        if alarm.id is None:
            time_str = f"{alarm.hour:02d}:{alarm.min:02d}"
            alarm.alarm_name = f"Alarm at {time_str}"
            self.alarm_clock_context.config.add_alarm_definition(alarm)
        else:
            self.alarm_clock_context.config.update_alarm_definition(alarm)

        self._editing_session = None
        return alarm

    def cancel_changes(self):
        if self._editing_session:
            self._editing_session.cancel()
            self._editing_session = None
