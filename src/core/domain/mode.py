from typing import List
import logging

from core.domain.model import (
    AlarmClockContext,
    HwButton,
    StreamAudioEffect,
    VisualEffect,
)
from core.interface.display.editor.alarm_definition_editor import AlarmDefinitionToEdit

from utils.events import TACEventPublisher
from utils.geolocation import GeoLocation
from utils.state_machine import State, StateMachine, StateTransition

logger = logging.getLogger("tac.domain")


class TacMode(State):

    alarm_clock_context: "AlarmClockContext"

    def __init__(
        self,
        previous_mode: "TacMode" = None,
        alarm_clock_context: "AlarmClockContext" = None,
    ):
        self.alarm_clock_context = alarm_clock_context
        if (previous_mode is not None) and (alarm_clock_context is None):
            self.alarm_clock_context = previous_mode.alarm_clock_context

    def __hash__(self):
        return self.__class__.__name__.__hash__()


class DefaultMode(TacMode):
    def __init__(
        self,
        previous_mode: TacMode = None,
        alarm_clock_context: "AlarmClockContext" = None,
    ):
        super().__init__(previous_mode, alarm_clock_context)


class AlarmViewMode(TacMode):
    alarm_index: int = 0

    def __init__(self, previous_mode: TacMode = None):
        super().__init__(previous_mode)
        if isinstance(previous_mode, AlarmViewMode):
            self.alarm_index = previous_mode.alarm_index

    def __str__(self):
        return f"{super().__str__()}(view: {self.alarm_index})"

    def get_active_alarm(self) -> AlarmDefinitionToEdit:
        ad: AlarmDefinitionToEdit = None
        if self.alarm_index < len(self.alarm_clock_context.config.alarm_definitions):
            ad = AlarmDefinitionToEdit(
                self.alarm_clock_context.config.alarm_definitions[self.alarm_index]
            )
        else:
            now = GeoLocation().now()
            ad = AlarmDefinitionToEdit()
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
        return ad

    def activate_next_alarm(self):
        if self.alarm_index < len(self.alarm_clock_context.config.alarm_definitions):
            self.alarm_index += 1
        else:
            self.alarm_index = 0
        return self.alarm_index

    def activate_previous_alarm(self):
        if self.alarm_index > 0:
            self.alarm_index -= 1
        else:
            self.alarm_index = len(self.alarm_clock_context.config.alarm_definitions)
        return self.alarm_index


class AlarmEditMode(AlarmViewMode):

    property_to_edit: str = "is_active"
    alarm_definition_in_editing: AlarmDefinitionToEdit = None

    def __init__(self, previous_mode: TacMode):
        super().__init__(previous_mode)
        if isinstance(previous_mode, AlarmEditMode):
            self.property_to_edit = previous_mode.property_to_edit
            self.alarm_definition_in_editing = previous_mode.alarm_definition_in_editing
        elif isinstance(previous_mode, AlarmViewMode):
            self.alarm_definition_in_editing = self.get_active_alarm()

    def __str__(self):
        return f"{super().__str__()}(edit: {self.property_to_edit})"

    def activate_next_property_to_edit(self):
        properties = self.alarm_definition_in_editing.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index + 1) % len(properties)]

    def activate_previous_property_to_edit(self):
        properties = self.alarm_definition_in_editing.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index - 1) % len(properties)]

    def is_in_edit_mode(self, properties: List[str]) -> bool:
        return self.property_to_edit in properties

    def start_editing(self):
        if self.property_to_edit == "update":
            self.update_config()
            self.proceedingState = AlarmViewMode
            return
        if self.property_to_edit == "cancel":
            self.proceedingState = AlarmViewMode
            return
        self.alarm_definition_in_editing.update_value_lists(
            self.alarm_clock_context.config,
            self.alarm_definition_in_editing.audio_effect.volume,
        )

    def update_config(self):
        if self.alarm_definition_in_editing.id is None:
            self.alarm_definition_in_editing.alarm_name = (
                "Alarm at " + self.alarm_definition_in_editing.to_time_string()
            )
            self.alarm_clock_context.config.add_alarm_definition(
                self.alarm_definition_in_editing
            )
        else:
            self.alarm_clock_context.config.update_alarm_definition(
                self.alarm_definition_in_editing
            )


class PropertyEditMode(AlarmEditMode):

    def __init__(self, previous_mode: AlarmEditMode):
        super().__init__(previous_mode)

    def __str__(self):
        return f"{super().__str__()}(value: {self.get_value()})"

    def get_value(self):
        return getattr(self.alarm_definition_in_editing, self.property_to_edit)

    def set_value(self, value):
        setattr(self.alarm_definition_in_editing, self.property_to_edit, value)

    def activate_next_value(self):
        value_list = self.alarm_definition_in_editing.get_editable_property(
            self.property_to_edit
        ).value_list
        current_index = 0
        try:
            current_index = value_list.index(self.get_value())
        except ValueError:
            pass

        self.set_value(value_list[(current_index + 1) % len(value_list)])

    def activate_previous_value(self):
        value_list = self.alarm_definition_in_editing.get_editable_property(
            self.property_to_edit
        ).value_list
        next_index = value_list.index(self.get_value()) - 1
        if next_index < 0:
            next_index = len(value_list) - 1
        self.set_value(value_list[next_index])


class AlarmClockStateMachine(StateMachine, TACEventPublisher):
    def __init__(
        self,
        default_state,
        alarm_view_state,
        alarm_edit_state,
        property_edit_state,
    ):
        default_mode = default_state
        alarm_view_mode = alarm_view_state
        alarm_edit_mode = alarm_edit_state
        property_edit_mode = property_edit_state

        StateMachine.__init__(self, default_mode)
        TACEventPublisher.__init__(self)

        super().add_definition(
            StateTransition(default_mode)
            .add_transition(HwButton("mode_button"), AlarmViewMode)
            .add_transition(
                HwButton("rotary_clockwise"),
                DefaultMode,
                source_state_updater=lambda su: self.publish(
                    reason="rotary_clockwise", during_registration=False
                ),
            )
            .add_transition(
                HwButton("rotary_counter_clockwise"),
                DefaultMode,
                source_state_updater=lambda su: self.publish(
                    reason="rotary_counter_clockwise", during_registration=False
                ),
            )
            .add_transition(
                HwButton("invoke_button"),
                DefaultMode,
                source_state_updater=lambda su: self.publish(
                    reason="invoke_button", during_registration=False
                ),
            )
        )

        super().add_definition(
            StateTransition(alarm_view_mode)
            .add_transition(HwButton("mode_button"), DefaultMode)
            .add_transition(
                HwButton("rotary_clockwise"),
                AlarmViewMode,
                source_state_updater=lambda su: su.activate_next_alarm(),
            )
            .add_transition(
                HwButton("rotary_counter_clockwise"),
                AlarmViewMode,
                source_state_updater=lambda su: su.activate_previous_alarm(),
            )
            .add_transition(HwButton("invoke_button"), AlarmEditMode)
        )

        super().add_definition(
            StateTransition(alarm_edit_mode)
            .add_transition(HwButton("mode_button"), DefaultMode)
            .add_transition(
                HwButton("rotary_clockwise"),
                AlarmEditMode,
                source_state_updater=lambda su: su.activate_next_property_to_edit(),
            )
            .add_transition(
                HwButton("rotary_counter_clockwise"),
                AlarmEditMode,
                source_state_updater=lambda su: su.activate_previous_property_to_edit(),
            )
            .add_transition(
                HwButton("invoke_button"),
                PropertyEditMode,
                source_state_updater=lambda su: su.start_editing(),
            )
        )

        super().add_definition(
            StateTransition(property_edit_mode)
            .add_transition(HwButton("mode_button"), DefaultMode)
            .add_transition(
                HwButton("rotary_clockwise"),
                PropertyEditMode,
                source_state_updater=lambda su: su.activate_next_value(),
            )
            .add_transition(
                HwButton("rotary_counter_clockwise"),
                PropertyEditMode,
                source_state_updater=lambda su: su.activate_previous_value(),
            )
            .add_transition(HwButton("invoke_button"), AlarmEditMode),
        )
