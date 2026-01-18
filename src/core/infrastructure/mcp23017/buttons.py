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

logger = logging.getLogger("tac.core.infrastructure.mcp.buttons")


class ButtonsManager:
    def __init__(self, mcp_manager: MCPManager, event_bus: EventBus = None):
        super().__init__()
        self.mcp_manager = mcp_manager
        self.event_bus = event_bus

        self.mcp_manager.add_callback(mode_button_channel, self._mode_button_callback)
        self.mcp_manager.add_callback(
            invoke_button_channel, self._invoke_button_callback
        )
        self.mcp_manager.setup()

        logger.info("MCP23017 initialized for button input with event interrupts.")

    def _mode_button_callback(self, pin_value: bool, _=None):
        self.event_bus.emit(
            HwButtonEvent(
                device_name=DeviceName.MODE_BUTTON,
                direction=ButtonDirection.DOWN if not pin_value else ButtonDirection.UP,
            )
        )

    def _invoke_button_callback(self, pin_value: bool, _=None):
        self.event_bus.emit(
            HwButtonEvent(
                device_name=DeviceName.INVOKE_BUTTON,
                direction=ButtonDirection.DOWN if not pin_value else ButtonDirection.UP,
            )
        )
