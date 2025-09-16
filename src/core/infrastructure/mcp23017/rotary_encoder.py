from i2c_devices import MCPManager
import logging
import threading
import time

logger = logging.getLogger("tac.rotary_encoder")


class RotaryEncoderManager:
    def __init__(self, on_clockwise, on_counter_clockwise):
        self.on_clockwise = on_clockwise
        self.on_counter_clockwise = on_counter_clockwise
        self.mcp = MCPManager().mcp
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._monitor)
        self._thread.daemon = True
        self._thread.start()

    def _monitor(self):
        pin_a = self.mcp.get_pin(8)  # B0
        pin_b = self.mcp.get_pin(9)  # B1
        pin_a.direction = 1  # input
        pin_b.direction = 1  # input
        pin_a.pull_up = True
        pin_b.pull_up = True
        last_state = (pin_a.value, pin_b.value)
        while not self._stop_event.is_set():
            state = (pin_a.value, pin_b.value)
            if state != last_state:
                if last_state == (1, 0) and state == (1, 1):
                    logger.debug("Rotary clockwise detected")
                    self.on_clockwise()
                elif last_state == (0, 1) and state == (1, 1):
                    logger.debug("Rotary counter-clockwise detected")
                    self.on_counter_clockwise()
                last_state = state
            time.sleep(0.005)

    def close(self):
        self._stop_event.set()
        self._thread.join()
