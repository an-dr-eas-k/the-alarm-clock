from enum import Enum
from typing import List, Union, Optional
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
from core.interface.display.editor.alarm_definition_editor import (
    AlarmDefinitionProperties,
)

from utils.geolocation import GeoLocation

logger = logging.getLogger("tac.mode_coordinator")


class ModeName(Enum):
    DEFAULT = "default"
    ALARM_VIEW = "alarm_view"
    ALARM_EDIT = "alarm_edit"
    PROPERTY_EDIT = "property_edit"

    def hash(self):
        return hash(self.value)


class TacMode:

    alarm_clock_context: "AlarmClockContext"

    def __init__(
        self,
        alarm_clock_context: "AlarmClockContext" = None,
    ):
        self.alarm_clock_context = alarm_clock_context


class DefaultMode(TacMode):
    def __init__(
        self,
        alarm_clock_context: "AlarmClockContext" = None,
    ):
        super().__init__(alarm_clock_context)


class AlarmEditingService(TacMode):
    alarm_index: int = -1
    property_to_edit: Union[AlarmProperty, EditorAction] = None
    alarm_definition_in_editing: AlarmDefinition = None
    alarm_definition_properties: AlarmDefinitionProperties = None

    def __init__(self, alarm_clock_context: "AlarmClockContext"):
        super().__init__(alarm_clock_context=alarm_clock_context)
        self.alarm_index = 0
        self.alarm_definition_in_editing = self.get_active_alarm()

    def __str__(self):
        return f"{super().__str__()}(edit: {self.property_to_edit})"

    def start_editing(self):
        self.alarm_definition_properties = AlarmDefinitionProperties()
        self.alarm_definition_properties.update_value_lists(
            self.alarm_clock_context.config,
            self.alarm_definition_in_editing.audio_effect.volume,
        )
        self.property_to_edit = self.get_properties_to_edit()[0]
        self.log_property_activation()

    def continue_editing(self):
        pass

    def start_property_value_editing(self) -> bool:
        value_list = self.alarm_definition_properties.get_editable_property(
            self.property_to_edit
        ).value_list
        if len(value_list) == 2:
            self._activate_next_value()
            return False
        return True

    def get_active_alarm(self) -> AlarmDefinition:
        ad: AlarmDefinition = None
        if self.alarm_index < len(self.alarm_clock_context.config.alarm_definitions):
            ad = self.alarm_clock_context.config.alarm_definitions[self.alarm_index]
        else:
            now = GeoLocation().now()
            ad = AlarmDefinition()
            ad.id = None
            ad.alarm_name = "New Alarm"
            ad.hour = now.hour
            ad.min = now.minute
            ad.is_active = True
            ad.recurring = None
            ad.onetime = now.date()
            if len(self.alarm_clock_context.config.audio_streams) > 0:
                ad.audio_effect = StreamAudioEffect(
                    stream_definition=self.alarm_clock_context.config.audio_streams[0],
                    volume=self.alarm_clock_context.config.default_volume,
                )
            ad.visual_effect = VisualEffect()
        logger.debug(f"Editing alarm: {ad.id}, {ad.alarm_name}")
        return ad

    def navigate_alarms(self, direction: int):
        if direction > 0:
            self._activate_next_alarm()
        else:
            self._activate_previous_alarm()

    def navigate_properties(self, direction: int):
        if direction > 0:
            self._activate_next_property_to_edit()
        else:
            self._activate_previous_property_to_edit()

    def navigate_value_list(self, direction: int):
        if direction > 0:
            self._activate_next_value()
        else:
            self._activate_previous_value()

    def _activate_next_alarm(self):
        if self.alarm_index < len(self.alarm_clock_context.config.alarm_definitions):
            self.alarm_index += 1
        else:
            self.alarm_index = 0
        self.alarm_definition_in_editing = self.get_active_alarm()
        return self.alarm_index

    def _activate_previous_alarm(self):
        if self.alarm_index > 0:
            self.alarm_index -= 1
        else:
            self.alarm_index = len(self.alarm_clock_context.config.alarm_definitions)
        self.alarm_definition_in_editing = self.get_active_alarm()
        return self.alarm_index

    def get_properties_to_edit(self) -> List[Union[AlarmProperty, EditorAction]]:
        return (
            self.alarm_definition_properties.get_properties_to_edit(
                self.alarm_definition_in_editing
            )
            + self.get_actions_to_edit()
        )

    def get_actions_to_edit(self) -> List[EditorAction]:
        return [EditorAction.COMMIT, EditorAction.CANCEL]

    def _activate_next_property_to_edit(self):
        properties = self.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index + 1) % len(properties)]
        self.log_property_activation()

    def _activate_previous_property_to_edit(self):
        properties = self.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index - 1) % len(properties)]
        self.log_property_activation()

    def log_property_activation(self):
        if self.property_to_edit in (EditorAction.COMMIT, EditorAction.CANCEL):
            logger.debug(f"Activated action to edit: {self.property_to_edit}")
            return
        logger.debug(
            f"Activated next property to edit: {self.property_to_edit}, current value: {self.get_value()}"
        )

    def is_in_edit_mode(self, properties: List[AlarmProperty]) -> bool:
        return self.property_to_edit in properties

    def update_config(self):
        if self.alarm_definition_in_editing.id is None:
            self.alarm_definition_in_editing.alarm_name = (
                "Alarm at " + self.alarm_definition_properties.to_time_string()
            )
            self.alarm_clock_context.config.add_alarm_definition(
                self.alarm_definition_in_editing
            )
        else:
            self.alarm_clock_context.config.update_alarm_definition(
                self.alarm_definition_in_editing
            )

    def get_value(self):
        return getattr(
            self.alarm_definition_in_editing, self.property_to_edit.name.lower()
        )

    def set_value(self, value):
        setattr(
            self.alarm_definition_in_editing, self.property_to_edit.name.lower(), value
        )

    def _activate_next_value(self):
        value_list = self.alarm_definition_properties.get_editable_property(
            self.property_to_edit
        ).value_list
        current_index = 0
        try:
            current_index = value_list.index(self.get_value())
        except ValueError:
            pass

        self.set_value(value_list[(current_index + 1) % len(value_list)])
        logger.debug(f"Activated next value: {self.get_value()}")

    def _activate_previous_value(self):
        value_list = self.alarm_definition_properties.get_editable_property(
            self.property_to_edit
        ).value_list
        next_index = value_list.index(self.get_value()) - 1
        if next_index < 0:
            next_index = len(value_list) - 1
        self.set_value(value_list[next_index])
        logger.debug(f"Activated previous value: {self.get_value()}")


class AlarmClockModeCoordinator:
    """
    Domain Entity: Coordinates UI modes and manages the alarm editing workflow.

    This is a pure domain component focused on business logic, not hardware events.
    Hardware event translation happens at the interface layer.
    """

    def __init__(
        self,
        event_bus,
        alarm_clock_context: AlarmClockContext,
    ):
        self.event_bus = event_bus
        self.alarm_clock_context = alarm_clock_context
        self._current_mode_name: ModeName = ModeName.DEFAULT
        self._editing_service: Optional[AlarmEditingService] = None

    @property
    def current_mode_name(self) -> ModeName:
        """Returns the current mode state."""
        return self._current_mode_name

    @property
    def editing_service(self) -> Optional[AlarmEditingService]:
        """Returns the active editing service, if in an editing mode."""
        return self._editing_service

    # ========== Domain Commands (called by interface layer) ==========

    def enter_alarm_view_mode(self):
        """Enter alarm viewing/selection mode."""
        logger.debug("Entering alarm view mode")
        self._editing_service = AlarmEditingService(self.alarm_clock_context)
        self._current_mode_name = ModeName.ALARM_VIEW

    def enter_alarm_edit_mode(self):
        """Enter alarm property editing mode."""
        if not self._editing_service:
            logger.warning("Cannot enter edit mode without an editing service")
            return

        logger.debug("Entering alarm edit mode")
        self._editing_service.start_editing()
        self._current_mode_name = ModeName.ALARM_EDIT

    def enter_property_edit_mode(self):
        """Enter property value editing mode."""
        logger.debug("Entering property edit mode")
        self._current_mode_name = ModeName.PROPERTY_EDIT

    def return_to_default_mode(self):
        """Return to default (clock display) mode."""
        logger.debug("Returning to default mode")
        self._editing_service = None
        self._current_mode_name = ModeName.DEFAULT

    def navigate_alarms(self, direction: int):
        """Navigate through alarm list in alarm view mode."""
        if self._current_mode_name != ModeName.ALARM_VIEW or not self._editing_service:
            return

        self._editing_service.navigate_alarms(direction)
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    def navigate_properties(self, direction: int):
        """Navigate through properties in alarm edit mode."""
        if self._current_mode_name != ModeName.ALARM_EDIT or not self._editing_service:
            return

        self._editing_service.navigate_properties(direction)

    def navigate_property_values(self, direction: int):
        """Navigate through values in property edit mode."""
        if (
            self._current_mode_name != ModeName.PROPERTY_EDIT
            or not self._editing_service
        ):
            return

        self._editing_service.navigate_value_list(direction)

    def handle_mode_button(self):
        """
        Handle mode button press - context-dependent behavior.
        Returns to default mode from any editing state.
        """
        if self._current_mode_name == ModeName.DEFAULT:
            # From default, enter alarm view
            self.enter_alarm_view_mode()
        else:
            # From any editing mode, return to default
            self.return_to_default_mode()

    def handle_invoke_button(self):
        """
        Handle invoke button press - context-dependent behavior.
        Advances through editing workflow or commits/cancels changes.
        """
        if self._current_mode_name == ModeName.DEFAULT:
            # In default mode, invoke button is handled elsewhere (toggle audio)
            return None

        elif self._current_mode_name == ModeName.ALARM_VIEW:
            # Start editing the selected alarm
            self.enter_alarm_edit_mode()

        elif self._current_mode_name == ModeName.ALARM_EDIT:
            # Handle property selection or action execution
            if not self._editing_service:
                return

            if self._editing_service.property_to_edit == EditorAction.COMMIT:
                self._commit_alarm_changes()
            elif self._editing_service.property_to_edit == EditorAction.CANCEL:
                self._cancel_alarm_changes()
            else:
                # Start editing property value
                if self._editing_service.start_property_value_editing():
                    self.enter_property_edit_mode()
                # else: value was toggled inline, stay in ALARM_EDIT

        elif self._current_mode_name == ModeName.PROPERTY_EDIT:
            # Finish editing property value
            if self._editing_service:
                self._editing_service.continue_editing()
            self._current_mode_name = ModeName.ALARM_EDIT

    # ========== Private Domain Logic ==========

    def _commit_alarm_changes(self):
        """Commit the edited alarm to the configuration."""
        if not self._editing_service:
            return

        self._editing_service.update_config()
        self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))
        self._current_mode_name = ModeName.ALARM_VIEW
        logger.info("Alarm changes committed")

    def _cancel_alarm_changes(self):
        """Cancel alarm editing and discard changes."""
        self._current_mode_name = ModeName.ALARM_VIEW
        logger.info("Alarm changes cancelled")
