from i2c_devices import MCPManager
import logging

logger = logging.getLogger("tac.rotary_encoder")


class RotaryEncoderManager:
    channel_a: int = 8
    channel_b: int = 9

    def __init__(self, on_clockwise, on_counter_clockwise):
        self.on_clockwise = on_clockwise
        self.on_counter_clockwise = on_counter_clockwise
        self.mcpManager = MCPManager()
        self.mcpManager.add_callback(
            self.mcpManager.rotary_encoder_channel_a, self._pin_callback
        )
        self.mcpManager.add_callback(
            self.mcpManager.rotary_encoder_channel_b, self._pin_callback
        )

    def _pin_callback(self, pin):
        channel_a_value = self.mcpManager.mcp.get_pin(
            self.mcpManager.rotary_encoder_channel_a
        ).value
        channel_b_value = self.mcpManager.mcp.get_pin(
            self.mcpManager.rotary_encoder_channel_b
        ).value

        state = (channel_a_value, channel_b_value)
        last_state = self.last_state
        if state != last_state:
            if last_state == (1, 0) and state == (1, 1):
                logger.debug("Rotary clockwise detected")
                self.on_clockwise()
            elif last_state == (0, 1) and state == (1, 1):
                logger.debug("Rotary counter-clockwise detected")
                self.on_counter_clockwise()
            self.last_state = state
