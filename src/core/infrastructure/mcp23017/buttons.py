from core.domain.model import HwButton
from core.infrastructure.i2c_devices import (
    MCPManager,
    mode_button_channel,
    invoke_button_channel,
)
import logging

from utils.events import TACEvent, TACEventPublisher

logger = logging.getLogger("tac.mcp_buttons")


class ButtonsManager(TACEventPublisher):
    def __init__(self):
        self.mcpManager = MCPManager()

        self.mcpManager.add_callback(mode_button_channel, self._mode_button_callback)
        self.mcpManager.add_callback(
            invoke_button_channel, self._invoke_button_callback
        )

        logger.info("MCP23017 initialized for button input with event interrupts.")

    def _mode_button_callback(self, mcp, pin):
        if (mcp.get_pin(pin).value) == 1:
            return
        self.publish(reason=HwButton("mode_button"), during_registration=False)

    def _invoke_button_callback(self, mcp, pin):
        if (mcp.get_pin(pin).value) == 1:
            return
        self.publish(reason=HwButton("invoke_button"), during_registration=False)
