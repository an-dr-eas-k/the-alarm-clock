from core.infrastructure.event_bus import EventBus
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
)
from core.infrastructure.i2c_devices import (
    MCPManager,
    mode_button_channel,
    invoke_button_channel,
)
import logging

logger = logging.getLogger("tac.mcp_buttons")


class ButtonsManager:
    def __init__(self, mcp_manager: MCPManager, event_bus: EventBus = None):
        super().__init__()
        self.mcpManager = mcp_manager
        self.event_bus = event_bus

        self.mcpManager.add_callback(mode_button_channel, self._mode_button_callback)
        self.mcpManager.add_callback(
            invoke_button_channel, self._invoke_button_callback
        )

        logger.info("MCP23017 initialized for button input with event interrupts.")

    def _mode_button_callback(self, pin: int, pin_value: bool):
        if pin != mode_button_channel:
            return
        self.event_bus.emit(
            HwButtonEvent(
                DeviceName.MODE_BUTTON,
                ButtonDirection.DOWN if not pin_value else ButtonDirection.UP,
            )
        )

    def _invoke_button_callback(self, pin: int, pin_value: bool):
        if pin != invoke_button_channel:
            return
        self.event_bus.emit(
            HwButtonEvent(
                DeviceName.INVOKE_BUTTON,
                ButtonDirection.DOWN if not pin_value else ButtonDirection.UP,
            )
        )
