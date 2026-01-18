from enum import Enum
from typing import Optional
import logging

from core.domain.alarm_definition_editor import AlarmEditingService, EditorAction
from core.domain.events import (
    ConfigChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
)
from core.infrastructure.event_bus import EventBus


logger = logging.getLogger("tac.core.domain.mode_coordinator")


class ModeName(Enum):
    DEFAULT = "default"
    ALARM_VIEW = "alarm_view"
    ALARM_EDIT = "alarm_edit"
    PROPERTY_EDIT = "property_edit"

    def hash(self):
        return hash(self.value)


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
