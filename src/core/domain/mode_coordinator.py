from enum import Enum
from typing import List, Union, Optional, TYPE_CHECKING
import logging

from core.domain.edit_mode import AlarmProperty, EditorAction
from core.domain.events import (
    ConfigChangedEvent,
    ForcedDisplayUpdateEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    StreamAudioEffect,
    VisualEffect,
)
from core.infrastructure.event_bus import EventBus
from core.interface.display.editor.alarm_definition_editor import (
    AlarmDefinitionProperties,
)

from utils.geolocation import GeoLocation

if TYPE_CHECKING:
    from core.domain.model import Config

logger = logging.getLogger("tac.core.domain.mode_coordinator")


class ModeName(Enum):
    DEFAULT = "default"
    ALARM_VIEW = "alarm_view"
    ALARM_EDIT = "alarm_edit"
    PROPERTY_EDIT = "property_edit"

    def hash(self):
        return hash(self.value)


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

    def _create_draft(self, alarm: AlarmDefinition) -> AlarmDefinition:
        return alarm

    def _build_property_list(self) -> List[Union[AlarmProperty, EditorAction]]:
        return self._property_editor.get_properties_to_edit(self._draft_alarm) + [
            EditorAction.COMMIT,
            EditorAction.CANCEL,
        ]

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
        return getattr(self._draft_alarm, self.current_property.name.lower())

    def change_property_value(self, value):
        if self.is_on_action:
            return

        old_value = self.get_current_value()
        setattr(self._draft_alarm, self.current_property.name.lower(), value)
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


class AlarmClockModeCoordinator:

    def __init__(
        self,
        event_bus: EventBus,
        alarm_clock_context: AlarmClockContext,
    ):
        self.event_bus: EventBus = event_bus
        self.alarm_clock_context = alarm_clock_context
        self._current_mode_name: ModeName = ModeName.DEFAULT
        self._editing_service: Optional[AlarmEditingService] = None

    @property
    def current_mode_name(self) -> ModeName:
        return self._current_mode_name

    @property
    def editing_service(self) -> Optional[AlarmEditingService]:
        return self._editing_service

    def enter_alarm_view_mode(self):
        logger.debug("Entering alarm view mode")
        self._editing_service = AlarmEditingService(self.alarm_clock_context)
        self._current_mode_name = ModeName.ALARM_VIEW

    def enter_alarm_edit_mode(self):
        if not self._editing_service:
            logger.warning("Cannot enter edit mode without an editing service")
            return

        logger.debug("Entering alarm edit mode")
        self._editing_service.start_editing()
        self._current_mode_name = ModeName.ALARM_EDIT

    def enter_property_edit_mode(self):
        logger.debug("Entering property edit mode")
        self._current_mode_name = ModeName.PROPERTY_EDIT

    def return_to_default_mode(self):
        logger.debug("Returning to default mode")
        self._editing_service = None
        self._current_mode_name = ModeName.DEFAULT

    def navigate_alarms(self, direction: int):
        if self._current_mode_name != ModeName.ALARM_VIEW or not self._editing_service:
            return

        self._editing_service.navigate_alarms(direction)
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    def navigate_properties(self, direction: int):
        if self._current_mode_name != ModeName.ALARM_EDIT or not self._editing_service:
            return

        self._editing_service.navigate_properties(direction)

    def navigate_property_values(self, direction: int):
        if (
            self._current_mode_name != ModeName.PROPERTY_EDIT
            or not self._editing_service
        ):
            return

        self._editing_service.navigate_value_list(direction)

    def handle_mode_button(self):
        if self._current_mode_name == ModeName.DEFAULT:
            self.enter_alarm_view_mode()
        else:
            self.return_to_default_mode()

    def handle_invoke_button(self):
        if self._current_mode_name == ModeName.DEFAULT:
            return None

        elif self._current_mode_name == ModeName.ALARM_VIEW:
            self.enter_alarm_edit_mode()

        elif self._current_mode_name == ModeName.ALARM_EDIT:
            if not self._editing_service:
                return

            if self._editing_service.property_to_edit == EditorAction.COMMIT:
                self._commit_alarm_changes()
            elif self._editing_service.property_to_edit == EditorAction.CANCEL:
                self._cancel_alarm_changes()
            else:
                if self._editing_service.start_property_value_editing():
                    self.enter_property_edit_mode()

        elif self._current_mode_name == ModeName.PROPERTY_EDIT:
            if self._editing_service:
                self._editing_service.continue_editing()
            self._current_mode_name = ModeName.ALARM_EDIT

    def _commit_alarm_changes(self):
        if not self._editing_service:
            return

        self._editing_service.commit_changes()
        self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))
        self._current_mode_name = ModeName.ALARM_VIEW
        logger.info("Alarm changes committed")

    def _cancel_alarm_changes(self):
        if self._editing_service:
            self._editing_service.cancel_changes()
        self._current_mode_name = ModeName.ALARM_VIEW
        logger.info("Alarm changes cancelled")
