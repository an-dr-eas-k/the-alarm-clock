from i2c_devices import MCPManager
import logging
import threading
import time

logger = logging.getLogger("tac.gpio_buttons")


class ButtonsManager:
    def __init__(self, button_configs):
        self.button_configs = button_configs
        self.mcpManager = MCPManager()
        for cfg in button_configs:
            pin_num = cfg["pin"]
            pin_callback = cfg["when_activated"]
            self.mcpManager.add_callback(pin_num, pin_callback)

        logger.info("MCP23017 initialized for button input with event interrupts.")
