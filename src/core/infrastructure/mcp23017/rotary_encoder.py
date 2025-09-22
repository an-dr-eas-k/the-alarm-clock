from core.domain.model import HwButton
from core.infrastructure.i2c_devices import (
    MCPManager,
    rotary_encoder_channel_a,
    rotary_encoder_channel_b,
)
import logging

from utils.events import TACEventPublisher

logger = logging.getLogger("tac.mcp_rotary_encoder")


class RotaryEncoderManager(TACEventPublisher):
    last_states = [(0, 0), (0, 0)]

    def __init__(self):
        super().__init__()
        self.mcpManager = MCPManager()
        self.mcpManager.add_callback(rotary_encoder_channel_a, self._pin_callback)
        self.mcpManager.add_callback(rotary_encoder_channel_b, self._pin_callback)
        logger.info(
            "MCP23017 initialized for rotary encoder input with event interrupts."
        )

    def _pin_callback(self, mcp, pin):
        channel_a_value = int(not mcp.get_pin(rotary_encoder_channel_a).value)
        channel_b_value = int(not mcp.get_pin(rotary_encoder_channel_b).value)

        state = (channel_a_value, channel_b_value)
        logger.debug(
            f"Rotary encoder current state: {state}, last state: {self.last_states[0]}"
        )

        last_state = self.last_states[0]
        if state != last_state:
            if state == (0, 0) and self.last_states[0] == (self.last_states[1])[::-1]:
                state = (1, 1)
                last_state = self.last_states[1]
                logger.debug(f"bouncing detected, new states are {state}, {last_state}")
            if last_state == (1, 0) and state == (1, 1):
                logger.debug("Rotary clockwise detected")
                self.publish(
                    reason=HwButton("rotary_clockwise"), during_registration=False
                )
            elif last_state == (0, 1) and state == (1, 1):
                logger.debug("Rotary counter-clockwise detected")
                self.publish(
                    reason=HwButton("rotary_counter_clockwise"),
                    during_registration=False,
                )
            self.last_states[1] = self.last_states[0]
            self.last_states[0] = state
