from core.infrastructure.event_bus import EventBus
from core.infrastructure.events_infrastructure import (
    DeviceName,
    HwRotaryEvent,
    HwRotaryEvent,
    RotaryDirection,
)
from core.infrastructure.i2c_devices import (
    MCPManager,
    rotary_encoder_channel_a,
    rotary_encoder_channel_b,
)
import logging


logger = logging.getLogger("tac.core.infrastructure.mcp.rotary_encoder")


class RotaryEncoderManager:
    last_states = [(0, 0), (0, 0)]

    def __init__(self, mcp_manager: MCPManager, event_bus: EventBus = None):
        super().__init__()
        self.mcp_manager = mcp_manager
        self.event_bus = event_bus
        self.mcp_manager.add_callback(rotary_encoder_channel_a, self._pin_callback)
        self.mcp_manager.add_callback(rotary_encoder_channel_b, lambda v, p: {})
        self.mcp_manager.setup()

        channel_a_value = int(
            not self.mcp_manager.mcp.get_pin(rotary_encoder_channel_a).value
        )
        channel_b_value = int(
            not self.mcp_manager.mcp.get_pin(rotary_encoder_channel_b).value
        )

        self.last_states = [(channel_a_value, channel_b_value), (None, None)]

        logger.info(
            f"MCP23017 initialized for rotary encoder input with event interrupts. Initial state: {self.last_states[0]}"
        )

    def _pin_callback(self, _: bool, pin_values=None):
        last_state = self.last_states[0]

        channel_a_value = pin_values[rotary_encoder_channel_a][0]
        if channel_a_value == last_state[0]:
            return

        channel_b_value = pin_values[rotary_encoder_channel_b][0]
        state = (channel_a_value, channel_b_value)
        logger.debug(
            f"Rotary encoder current state: {state}, last state: {self.last_states[0]}"
        )

        if channel_b_value != channel_a_value:
            logger.debug("Rotary clockwise detected")

            self.event_bus.emit(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE)
            )
        else:
            logger.debug("Rotary counter-clockwise detected")
            self.event_bus.emit(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE
                )
            )

        self.last_states[1] = self.last_states[0]
        self.last_states[0] = state
