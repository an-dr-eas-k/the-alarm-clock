from enum import Enum
from typing import List
import logging

from core.domain.events import (
    ConfigChangedEvent,
    ForcedDisplayUpdateEvent,
    ToggleAudioEvent,
    VolumeChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    StreamAudioEffect,
    VisualEffect,
)
from core.infrastructure.events_infrastructure import (
    DeviceName,
    HwButtonEvent,
    HwRotaryEvent,
    RotaryDirection,
)
from core.interface.display.editor.alarm_definition_editor import AlarmDefinitionToEdit

from utils.geolocation import GeoLocation
from utils.state_machine import State, StateMachine, StateTransition

logger = logging.getLogger("tac.domain")


class ModeName(Enum):
    DEFAULT = "default"
    ALARM_VIEW = "alarm_view"
    ALARM_EDIT = "alarm_edit"
    PROPERTY_EDIT = "property_edit"

    def hash(self):
        return hash(self.value)


class TacMode(State):

    alarm_clock_context: "AlarmClockContext"
    mode_name: ModeName

    def __init__(
        self,
        alarm_clock_context: "AlarmClockContext" = None,
    ):
        self.alarm_clock_context = alarm_clock_context

    def __hash__(self):
        return self.mode_name.hash()


class DefaultMode(TacMode):
    def __init__(
        self,
        alarm_clock_context: "AlarmClockContext" = None,
    ):
        super().__init__(alarm_clock_context)
        self.mode_name = ModeName.DEFAULT


class AlarmEditor(TacMode):
    alarm_index: int = -1
    property_to_edit: str = None
    alarm_definition_in_editing: AlarmDefinition = None
    alarm_definition_values: AlarmDefinitionToEdit = None

    def __init__(self, alarm_clock_context: "AlarmClockContext"):
        super().__init__(alarm_clock_context=alarm_clock_context)

    def __str__(self):
        return f"{super().__str__()}(edit: {self.property_to_edit})"

    def initialize(self) -> "AlarmEditor":
        self.alarm_index = 0
        self.alarm_definition_in_editing = self.get_active_alarm()
        self.mode_name = ModeName.ALARM_VIEW
        return self

    def start_editing(self) -> "AlarmEditor":
        self.mode_name = ModeName.ALARM_EDIT
        # if self.property_to_edit == "update":
        #     self.update_config()
        #     self.proceedingState = AlarmViewMode
        #     return
        # if self.property_to_edit == "cancel":
        #     self.proceedingState = AlarmViewMode
        #     return
        self.alarm_definition_values.update_value_lists(
            self.alarm_clock_context.config,
            self.alarm_definition_in_editing.audio_effect.volume,
        )
        self.property_to_edit = self.alarm_definition_values.get_properties_to_edit()[0]
        return self

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
        return ad

    def activate_next_alarm(self):
        if self.alarm_index < len(self.alarm_clock_context.config.alarm_definitions):
            self.alarm_index += 1
        else:
            self.alarm_index = 0
        self.alarm_definition_in_editing = self.get_active_alarm()
        return self.alarm_index

    def activate_previous_alarm(self):
        if self.alarm_index > 0:
            self.alarm_index -= 1
        else:
            self.alarm_index = len(self.alarm_clock_context.config.alarm_definitions)
        self.alarm_definition_in_editing = self.get_active_alarm()
        return self.alarm_index

    def activate_next_property_to_edit(self):
        properties = self.alarm_definition_values.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index + 1) % len(properties)]

    def activate_previous_property_to_edit(self):
        properties = self.alarm_definition_values.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index - 1) % len(properties)]

    def is_in_edit_mode(self, properties: List[str]) -> bool:
        return self.property_to_edit in properties

    def update_config(self):
        if self.alarm_definition_in_editing.id is None:
            self.alarm_definition_in_editing.alarm_name = (
                "Alarm at " + self.alarm_definition_values.to_time_string()
            )
            self.alarm_clock_context.config.add_alarm_definition(
                self.alarm_definition_in_editing
            )
        else:
            self.alarm_clock_context.config.update_alarm_definition(
                self.alarm_definition_in_editing
            )

    def get_value(self):
        return getattr(self.alarm_definition_in_editing, self.property_to_edit)

    def set_value(self, value):
        setattr(self.alarm_definition_in_editing, self.property_to_edit, value)

    def activate_next_value(self):
        value_list = self.alarm_definition_values.get_editable_property(
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


class AlarmClockModeCoordinator(StateMachine):
    def __init__(
        self,
        event_bus,
        default_mode,
        alarm_edit_mode,
    ):
        self.default_mode: DefaultMode = default_mode
        self.alarm_edit_mode: "AlarmEditor" = alarm_edit_mode
        super().__init__(event_bus, default_mode)
        self.event_bus.on(HwButtonEvent)(super()._transition_state)
        self.event_bus.on(HwRotaryEvent)(super()._transition_state)

        super().add_definition(
            StateTransition(ModeName.DEFAULT.hash())
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON),
                new_state_type=lambda _: self.alarm_edit_mode.initialize(),
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                new_state_type=None,
                eventToEmit=ToggleAudioEvent(),
            )
            .add_transition(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE),
                new_state_type=None,
                eventToEmit=VolumeChangedEvent(+1),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.COUNTERCLOCKWISE,
                ),
                new_state_type=None,
                eventToEmit=VolumeChangedEvent(-1),
            )
        )

        super().add_definition(
            StateTransition(ModeName.ALARM_VIEW.hash())
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON), lambda _: self.default_mode
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                new_state_type=None,
                source_state_updater=lambda state: state.start_editing(),
            )
            .add_transition(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE),
                new_state_type=None,
                source_state_updater=lambda state: state.activate_next_alarm(),
                eventToEmit=ForcedDisplayUpdateEvent(),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.COUNTERCLOCKWISE,
                ),
                new_state_type=None,
                source_state_updater=lambda state: state.activate_previous_alarm(),
                eventToEmit=ForcedDisplayUpdateEvent(),
            )
        )

        super().add_definition(
            StateTransition(ModeName.ALARM_EDIT.hash())
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON), lambda _: self.default_mode
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                new_state_type=lambda _: self.default_mode,
                source_state_updater=lambda su: su.start_editing(),
                eventToEmit=ConfigChangedEvent(
                    self.default_mode.alarm_clock_context.config
                ),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.CLOCKWISE,
                ),
                new_state_type=None,
                source_state_updater=lambda state: state.activate_next_property_to_edit(),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE
                ),
                new_state_type=None,
                source_state_updater=lambda state: state.activate_previous_property_to_edit(),
            )
        )

        super().add_definition(
            StateTransition(ModeName.PROPERTY_EDIT.hash())
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON), lambda _: self.default_mode
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                new_state_type=lambda state: state.continue_editing(),
            )
            .add_transition(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE),
                new_state_type=None,
                source_state_updater=lambda su: su.activate_next_value(),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.COUNTERCLOCKWISE,
                ),
                new_state_type=None,
                source_state_updater=lambda su: su.activate_previous_value(),
            )
        )
