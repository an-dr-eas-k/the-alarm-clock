import logging
from dataclasses import dataclass
from typing import Optional

from utils.state_machine import State, StateTransition, StateMachine
from core.domain.events import (
    EnterDefault,
    EnterAlarmView,
    StartAlarmEdit,
    StartPropertyEdit,
    FocusNextAlarm,
    FocusPreviousAlarm,
    FocusNextProperty,
    FocusPreviousProperty,
    FocusNextValue,
    FocusPreviousValue,
    CommitAlarmEdit,
    CancelAlarmEdit,
    DomainTrigger,
)
from core.domain.alarm_editor import AlarmEditor

logger = logging.getLogger("tac.domain.mode_state_machine")


# Domain States (reduced responsibilities)
@dataclass
class ModeState(State):
    name: str

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name


class DefaultMode(ModeState):
    def __init__(self):
        super().__init__("default")


class AlarmViewMode(ModeState):
    def __init__(self):
        super().__init__("alarm_view")


class AlarmEditMode(ModeState):
    def __init__(self):
        super().__init__("alarm_edit")


class PropertyEditMode(ModeState):
    def __init__(self):
        super().__init__("property_edit")


class DomainModeStateMachine(StateMachine):
    """Pure domain state machine: transitions driven by DomainTriggers, delegating editing logic to AlarmEditor."""

    def __init__(self, alarm_editor: AlarmEditor):
        self._alarm_editor = alarm_editor
        super().__init__(DefaultMode())
        self._define_transitions()

    def _define_transitions(self):
        # Default
        self.add_definition(
            StateTransition(DefaultMode()).add_transition(
                EnterAlarmView(), AlarmViewMode
            )
        )

        # Alarm View
        self.add_definition(
            StateTransition(AlarmViewMode())
            .add_transition(EnterDefault(), DefaultMode)
            .add_transition(
                FocusNextAlarm(),
                AlarmViewMode,
                lambda s: self._alarm_editor.select_next_alarm(),
            )
            .add_transition(
                FocusPreviousAlarm(),
                AlarmViewMode,
                lambda s: self._alarm_editor.select_previous_alarm(),
            )
            .add_transition(
                StartAlarmEdit(),
                AlarmEditMode,
                lambda s: self._alarm_editor.start_edit(),
            )
        )

        # Alarm Edit
        self.add_definition(
            StateTransition(AlarmEditMode())
            .add_transition(EnterDefault(), DefaultMode)
            .add_transition(
                FocusNextProperty(),
                AlarmEditMode,
                lambda s: self._alarm_editor.focus_next_property(),
            )
            .add_transition(
                FocusPreviousProperty(),
                AlarmEditMode,
                lambda s: self._alarm_editor.focus_previous_property(),
            )
            .add_transition(StartPropertyEdit(), PropertyEditMode)
            .add_transition(
                CommitAlarmEdit(), AlarmViewMode, lambda s: self._alarm_editor.commit()
            )
            .add_transition(
                CancelAlarmEdit(), AlarmViewMode, lambda s: self._alarm_editor.cancel()
            )
        )

        # Property Edit
        self.add_definition(
            StateTransition(PropertyEditMode())
            .add_transition(EnterDefault(), DefaultMode)
            .add_transition(
                FocusNextValue(),
                PropertyEditMode,
                lambda s: self._alarm_editor.focus_next_value(),
            )
            .add_transition(
                FocusPreviousValue(),
                PropertyEditMode,
                lambda s: self._alarm_editor.focus_previous_value(),
            )
            .add_transition(
                StartAlarmEdit(), AlarmEditMode
            )  # back to property list view
            .add_transition(
                CommitAlarmEdit(), AlarmViewMode, lambda s: self._alarm_editor.commit()
            )
            .add_transition(
                CancelAlarmEdit(), AlarmViewMode, lambda s: self._alarm_editor.cancel()
            )
        )

    def fire(self, trigger: DomainTrigger):
        from utils.events import TACEvent

        # Wrap DomainTrigger in TACEvent for compatibility with base handle
        observation = TACEvent(
            publisher=self,
            property_name="mode",
            reason=trigger,
            during_registration=False,
        )
        state_before = self.current_state
        new_state = self.handle(observation)
        return state_before, new_state
