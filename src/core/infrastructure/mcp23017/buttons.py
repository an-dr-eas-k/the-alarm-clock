from i2c_devices import MCPManager
import logging

logger = logging.getLogger("tac.mcp_buttons")


class ButtonsManager:
    def __init__(self, button_configs):
        self.button_configs = button_configs
        self.mcpManager = MCPManager()
        for cfg in button_configs:
            self.mcpManager.add_callback(cfg["pin"], cfg["when_activated"])

        logger.info("MCP23017 initialized for button input with event interrupts.")
