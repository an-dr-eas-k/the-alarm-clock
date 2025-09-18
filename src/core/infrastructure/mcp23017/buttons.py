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

        self.mcpManager.add_callback(mode_button_channel, mode_channel_callback)
        self.mcpManager.add_callback(invoke_button_channel, invoke_channel_callback)

        logger.info("MCP23017 initialized for button input with event interrupts.")
