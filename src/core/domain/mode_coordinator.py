from enum import Enum
from typing import List, Union
import logging

from core.domain.edit_mode import AlarmProperty, EditorAction
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
from core.interface.display.editor.alarm_definition_editor import (
    AlarmDefinitionProperties,
)

from utils.geolocation import GeoLocation
from utils.state_machine import State, StateMachine, StateTransition

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


class AlarmEditor(TacMode):
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
            self.activate_next_value()
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

    def get_properties_to_edit(self) -> List[Union[AlarmProperty, EditorAction]]:
        return (
            self.alarm_definition_properties.get_properties_to_edit(
                self.alarm_definition_in_editing
            )
            + self.get_actions_to_edit()
        )

    def get_actions_to_edit(self) -> List[EditorAction]:
        return [EditorAction.COMMIT, EditorAction.CANCEL]

    def activate_next_property_to_edit(self):
        properties = self.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index + 1) % len(properties)]
        self.log_property_activation()

    def log_property_activation(self):
        if self.property_to_edit in (EditorAction.COMMIT, EditorAction.CANCEL):
            logger.debug(f"Activated action to edit: {self.property_to_edit}")
            return
        logger.debug(
            f"Activated next property to edit: {self.property_to_edit}, current value: {self.get_value()}"
        )

    def activate_previous_property_to_edit(self):
        properties = self.get_properties_to_edit()
        current_index = properties.index(self.property_to_edit)
        self.property_to_edit = properties[(current_index - 1) % len(properties)]
        self.log_property_activation()

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

    def activate_next_value(self):
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

    def activate_previous_value(self):
        value_list = self.alarm_definition_properties.get_editable_property(
            self.property_to_edit
        ).value_list
        next_index = value_list.index(self.get_value()) - 1
        if next_index < 0:
            next_index = len(value_list) - 1
        self.set_value(value_list[next_index])
        logger.debug(f"Activated previous value: {self.get_value()}")


class AlarmClockModeCoordinator(StateMachine):
    def __init__(
        self,
        event_bus,
        alarm_clock_context: AlarmClockContext,
    ):
        self.alarm_clock_context = alarm_clock_context
        self.current_mode: TacMode = DefaultMode(
            alarm_clock_context=alarm_clock_context
        )
        super().__init__(event_bus, ModeName.DEFAULT)
        self.event_bus.on(HwButtonEvent)(super()._transition_state)
        self.event_bus.on(HwRotaryEvent)(super()._transition_state)

        super().add_definition(
            StateTransition(ModeName.DEFAULT)
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON),
                callable=lambda _: self.init_alarm_editor_mode(),
                next_state=ModeName.ALARM_VIEW,
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                eventToEmit=ToggleAudioEvent(),
            )
            .add_transition(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE),
                eventToEmit=VolumeChangedEvent(+1),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.COUNTERCLOCKWISE,
                ),
                eventToEmit=VolumeChangedEvent(-1),
            )
        )

        super().add_definition(
            StateTransition(ModeName.ALARM_VIEW)
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON),
                callable=lambda _: self.init_default_mode(),
                next_state=ModeName.DEFAULT,
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                next_state=ModeName.ALARM_EDIT,
                callable=lambda _: (
                    self.current_mode.start_editing()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
            .add_transition(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE),
                callable=lambda _: (
                    self.current_mode.activate_next_alarm()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
                eventToEmit=ForcedDisplayUpdateEvent(),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.COUNTERCLOCKWISE,
                ),
                callable=lambda _: (
                    self.current_mode.activate_previous_alarm()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
                eventToEmit=ForcedDisplayUpdateEvent(),
            )
        )

        super().add_definition(
            StateTransition(ModeName.ALARM_EDIT)
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON),
                callable=lambda _: self.init_default_mode(),
                next_state=ModeName.DEFAULT,
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                next_state=lambda _: (
                    self.handle_invoke_in_alarm_edit_mode(self.current_mode)
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.CLOCKWISE,
                ),
                callable=lambda _: (
                    self.current_mode.activate_next_property_to_edit()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE
                ),
                callable=lambda _: (
                    self.current_mode.activate_previous_property_to_edit()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
        )

        super().add_definition(
            StateTransition(ModeName.PROPERTY_EDIT)
            .add_transition(
                HwButtonEvent(DeviceName.MODE_BUTTON), next_state=ModeName.DEFAULT
            )
            .add_transition(
                HwButtonEvent(DeviceName.INVOKE_BUTTON),
                next_state=ModeName.ALARM_EDIT,
                callable=lambda _: (
                    self.current_mode.continue_editing()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
            .add_transition(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE),
                callable=lambda _: (
                    self.current_mode.activate_next_value()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
            .add_transition(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER,
                    RotaryDirection.COUNTERCLOCKWISE,
                ),
                callable=lambda _: (
                    self.current_mode.activate_previous_value()
                    if isinstance(self.current_mode, AlarmEditor)
                    else None
                ),
            )
        )

    def handle_invoke_in_alarm_edit_mode(self, state: AlarmEditor):
        if state.property_to_edit == EditorAction.COMMIT:
            state.update_config()
            self.event_bus.emit(ConfigChangedEvent(self.alarm_clock_context.config))
            return ModeName.ALARM_VIEW
        elif state.property_to_edit == EditorAction.CANCEL:
            return ModeName.ALARM_VIEW
        else:
            if state.start_property_value_editing():
                return ModeName.PROPERTY_EDIT
            else:
                return ModeName.ALARM_EDIT

    def init_alarm_editor_mode(self) -> "AlarmEditor":
        self.current_mode = AlarmEditor(self.alarm_clock_context)

    def init_default_mode(self) -> "AlarmEditor":
        self.current_mode = AlarmEditor(self.alarm_clock_context)
