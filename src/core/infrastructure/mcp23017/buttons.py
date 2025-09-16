from i2c_devices import MCPManager
import logging
import threading
import time

logger = logging.getLogger("tac.gpio_buttons")


class ButtonsManager:
    def __init__(self, button_configs):
        self.button_configs = button_configs
        self.mcp = MCPManager().mcp
        self._stop_event = threading.Event()
        self._last_activation = {}  # pin_num: timestamp
        for cfg in button_configs:
            pin_num = cfg["pin"]
            pin = self.mcp.get_pin(pin_num)
            pin.direction = 1  # input
            pin.pull_up = True
            if "when_activated" in cfg:
                pin.interrupt_enable = True
                pin.interrupt_callback = lambda p=pin, cb=cfg[
                    "when_activated"
                ]: self._handle_activation(p, cb)
        logger.info("MCP23017 initialized for button input with event interrupts.")

    def _handle_activation(self, pin, callback):
        debounce_ms = 30
        now = time.monotonic() * 1000
        pin_num = pin.pin
        last = self._last_activation.get(pin_num, 0)
        if now - last < debounce_ms:
            return
        self._last_activation[pin_num] = now
        if pin.value == 0:
            callback()

    def close(self):
        self._stop_event.set()
        # No cleanup needed for MCP23017
