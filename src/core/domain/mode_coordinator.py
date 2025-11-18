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
from core.interface.display.editor.alarm_definition_editor import (
    AlarmDefinitionProperties,
)

from utils.geolocation import GeoLocation

if TYPE_CHECKING:
    from core.domain.model import Config

logger = logging.getLogger("tac.mode_coordinator")


class ModeName(Enum):
    DEFAULT = "default"
    ALARM_VIEW = "alarm_view"
    ALARM_EDIT = "alarm_edit"
    PROPERTY_EDIT = "property_edit"

    def hash(self):
        return hash(self.value)


class AlarmEditingSession:
    """
    Domain Aggregate: Represents an in-progress alarm editing session.

    This encapsulates the business logic for editing an alarm, including
    validation, property navigation, and change tracking.
    """

    def __init__(self, alarm: AlarmDefinition, config: "Config"):
        self._original_alarm = alarm
        self._draft_alarm = self._create_draft(alarm)
        self._current_property_index = 0
        self._properties = self._build_property_list()
        self._property_editor = AlarmDefinitionProperties()
        self._property_editor.update_value_lists(
            config, self._draft_alarm.audio_effect.volume
        )

    def _create_draft(self, alarm: AlarmDefinition) -> AlarmDefinition:
        """Create a working copy of the alarm for editing."""
        # In a more sophisticated implementation, this would be a proper copy
        return alarm

    def _build_property_list(self) -> List[Union[AlarmProperty, EditorAction]]:
        """Build the list of editable properties based on alarm state."""
        return self._property_editor.get_properties_to_edit(self._draft_alarm) + [
            EditorAction.COMMIT,
            EditorAction.CANCEL,
        ]

    @property
    def draft_alarm(self) -> AlarmDefinition:
        """The alarm being edited."""
        return self._draft_alarm

    @property
    def current_property(self) -> Union[AlarmProperty, EditorAction]:
        """The currently selected property or action."""
        return self._properties[self._current_property_index]

    @property
    def is_on_action(self) -> bool:
        """Returns true if currently on COMMIT or CANCEL action."""
        return isinstance(self.current_property, EditorAction)

    def navigate_property(self, direction: int):
        """Navigate to the next or previous property."""
        self._properties = (
            self._build_property_list()
        )  # Rebuild in case recurrence changed
        self._current_property_index = (self._current_property_index + direction) % len(
            self._properties
        )
        logger.debug(f"Navigated to property: {self.current_property}")

    def get_property_values(self) -> List:
        """Get the list of possible values for the current property."""
        if self.is_on_action:
            return []
        return self._property_editor.get_editable_property(
            self.current_property
        ).value_list

    def get_current_value(self):
        """Get the current value of the selected property."""
        if self.is_on_action:
            return None
        return getattr(self._draft_alarm, self.current_property.name.lower())

    def change_property_value(self, value):
        """Change the value of the current property."""
        if self.is_on_action:
            return

        old_value = self.get_current_value()
        setattr(self._draft_alarm, self.current_property.name.lower(), value)
        logger.debug(f"Changed {self.current_property} from {old_value} to {value}")

        # Rebuild property list if recurrence changed (affects which properties are shown)
        if self.current_property == AlarmProperty.RECURRENCY:
            self._properties = self._build_property_list()

    def navigate_value(self, direction: int):
        """Navigate to the next or previous value for the current property."""
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
        """Determine if we should enter a separate value editing mode."""
        if self.is_on_action:
            return False
        values = self.get_property_values()
        # If only 2 values (like boolean), toggle inline instead of entering edit mode
        return len(values) != 2

    def commit(self) -> AlarmDefinition:
        """Commit the changes and return the edited alarm."""
        logger.info(f"Committing alarm changes: {self._draft_alarm.alarm_name}")
        return self._draft_alarm

    def cancel(self):
        """Cancel the editing session and discard changes."""
        logger.info(f"Cancelling alarm changes")


class AlarmEditingService:
    """
    Application Service: Orchestrates alarm editing workflow.

    Manages the lifecycle of editing sessions and coordinates between
    the domain layer (AlarmEditingSession) and the application needs.
    """

    def __init__(self, alarm_clock_context: "AlarmClockContext"):
        self.alarm_clock_context = alarm_clock_context
        self._alarm_index = 0
        self._editing_session: Optional[AlarmEditingSession] = None

    @property
    def current_alarm_index(self) -> int:
        """The index of the currently selected alarm."""
        return self._alarm_index

    @property
    def current_alarm(self) -> AlarmDefinition:
        """The alarm currently being viewed or edited."""
        return self._get_alarm_at_index(self._alarm_index)

    @property
    def editing_session(self) -> Optional[AlarmEditingSession]:
        """The active editing session, if any."""
        return self._editing_session

    @property
    def property_to_edit(self) -> Optional[Union[AlarmProperty, EditorAction]]:
        """For backward compatibility with display code."""
        return self._editing_session.current_property if self._editing_session else None

    @property
    def alarm_definition_in_editing(self) -> Optional[AlarmDefinition]:
        """For backward compatibility with display code."""
        return (
            self._editing_session.draft_alarm
            if self._editing_session
            else self.current_alarm
        )

    def start_editing(self):
        """Start editing the currently selected alarm."""
        alarm = self.current_alarm
        self._editing_session = AlarmEditingSession(
            alarm, self.alarm_clock_context.config
        )
        logger.debug(f"Started editing session for: {alarm.alarm_name}")

    def continue_editing(self):
        """Continue editing after a property value change."""
        # No-op: session maintains its own state
        pass

    def start_property_value_editing(self) -> bool:
        """Check if we should enter value editing mode."""
        if not self._editing_session:
            return False

        # For 2-value properties, toggle inline
        values = self._editing_session.get_property_values()
        if len(values) == 2:
            self._editing_session.navigate_value(1)
            return False

        return self._editing_session.should_enter_value_edit_mode()

    def _get_alarm_at_index(self, index: int) -> AlarmDefinition:
        """Get the alarm at the specified index, or create a new one."""
        alarms = self.alarm_clock_context.config.alarm_definitions

        if index < len(alarms):
            return alarms[index]

        # Create new alarm if index is beyond existing alarms
        return self._create_new_alarm()

    def _create_new_alarm(self) -> AlarmDefinition:
        """Factory method to create a new alarm with sensible defaults."""
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
                stream_definition=self.alarm_clock_context.config.audio_streams[0],
                volume=self.alarm_clock_context.config.default_volume,
            )
        alarm.visual_effect = VisualEffect()

        logger.debug(f"Created new alarm template")
        return alarm

    def navigate_alarms(self, direction: int):
        """Navigate through the list of alarms."""
        max_index = len(self.alarm_clock_context.config.alarm_definitions)
        self._alarm_index = (self._alarm_index + direction) % (max_index + 1)
        logger.debug(f"Navigated to alarm index: {self._alarm_index}")

    def navigate_properties(self, direction: int):
        """Navigate through properties in the editing session."""
        if self._editing_session:
            self._editing_session.navigate_property(direction)

    def navigate_value_list(self, direction: int):
        """Navigate through values for the current property."""
        if self._editing_session:
            self._editing_session.navigate_value(direction)

    def is_in_edit_mode(self, properties: List[AlarmProperty]) -> bool:
        """Check if currently editing one of the specified properties."""
        return self.property_to_edit in properties if self.property_to_edit else False

    def commit_changes(self) -> AlarmDefinition:
        """Commit the editing session and save to config."""
        if not self._editing_session:
            return None

        alarm = self._editing_session.commit()

        # Save to configuration (repository pattern would be better)
        if alarm.id is None:
            # Generate name for new alarm
            time_str = f"{alarm.hour:02d}:{alarm.min:02d}"
            alarm.alarm_name = f"Alarm at {time_str}"
            self.alarm_clock_context.config.add_alarm_definition(alarm)
        else:
            self.alarm_clock_context.config.update_alarm_definition(alarm)

        self._editing_session = None
        return alarm

    def cancel_changes(self):
        """Cancel the editing session and discard changes."""
        if self._editing_session:
            self._editing_session.cancel()
            self._editing_session = None


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

        self._editing_service.commit_changes()
        self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))
        self._current_mode_name = ModeName.ALARM_VIEW
        logger.info("Alarm changes committed")

    def _cancel_alarm_changes(self):
        """Cancel alarm editing and discard changes."""
        if self._editing_service:
            self._editing_service.cancel_changes()
        self._current_mode_name = ModeName.ALARM_VIEW
        logger.info("Alarm changes cancelled")
