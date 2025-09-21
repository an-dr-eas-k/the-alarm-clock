from core.infrastructure.i2c_devices import (
    MCPManager,
    mode_button_channel,
    invoke_button_channel,
)
import logging

logger = logging.getLogger("tac.mcp_buttons")


class ButtonsManager:
    def __init__(self, mode_channel_callback, invoke_channel_callback):
        self.mcpManager = MCPManager()

        self.on_mode_channel_callback = mode_channel_callback
        self.on_invoke_channel_callback = invoke_channel_callback

        self.mcpManager.add_callback(mode_button_channel, self._mode_button_callback)
        self.mcpManager.add_callback(
            invoke_button_channel, self._invoke_button_callback
        )

        logger.info("MCP23017 initialized for button input with event interrupts.")

    def _mode_button_callback(self, mcp, pin):
        if (mcp.get_pin(pin).value) == 1:
            return
        self.on_mode_channel_callback()

    def _invoke_button_callback(self, mcp, pin):
        if (mcp.get_pin(pin).value) == 1:
            return
        self.on_invoke_channel_callback()
