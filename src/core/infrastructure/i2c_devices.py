import logging
import time
from concurrent.futures import ThreadPoolExecutor
import board
import busio
from digitalio import Direction, Pull
from adafruit_mcp230xx.mcp23017 import MCP23017


rotary_encoder_channel_press: int = 8
rotary_encoder_channel_a: int = 10
rotary_encoder_channel_b: int = 9
mode_button_channel: int = 0
invoke_button_channel: int = 1

interrupt_pin: int = 4


def GPIO_Module():
    from RPi import GPIO  # type: ignore

    return GPIO


class I2CManager:
    def __init__(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)


logger = logging.getLogger("tac.core.infrastructure.mcp")


class MCPManager:
    last_log_time = 0

    def __init__(self, i2c_manager: I2CManager, executor: ThreadPoolExecutor):

        self.mcp = MCP23017(i2c_manager.i2c)
        self.executor = executor
        self.mcp_callbacks = {}

    def setup(self):
        configured_pins = self.mcp_callbacks.keys()
        logger.info(f"Configuring MCP23017 pins: {configured_pins}")

        for i in configured_pins:
            pin = self.mcp.get_pin(i)
            pin.direction = Direction.INPUT
            pin.pull = Pull.UP

        mask = sum(1 << pin for pin in configured_pins)

        logger.info(f"Hexadecimal bitmask: {hex(mask)}")
        self.mcp.interrupt_enable = mask

        self.mcp.interrupt_configuration = 0x0000  # notify me, when any value changes
        self.mcp.gppu = mask  # enable pull-ups on all used pins
        self.mcp.io_control = (
            0x44  # 0100 0100 # mirroring INT pins, open drain, active low
        )

        self.mcp.clear_ints()

        GPIO_Module().setmode(GPIO_Module().BCM)
        GPIO_Module().setup(interrupt_pin, GPIO_Module().IN, GPIO_Module().PUD_UP)
        GPIO_Module().add_event_detect(
            interrupt_pin,
            GPIO_Module().FALLING,
            callback=self.gpio_event_detected,
            bouncetime=10,
        )

        self.mcp.clear_ints()

        # if logger.level == logging.DEBUG:
        #     self.executor.submit(self._log_thread_callback)

    def add_callback(self, pin_num, callback):
        self.mcp_callbacks[pin_num] = callback

    def _log_thread_callback(self):
        while True:
            logger.debug(
                f"interrupt state: {int(GPIO_Module().input(interrupt_pin))}, mcp pin states: "
                + ", ".join(
                    [f"{p:02}: {int(self.mcp.get_pin(p).value)}" for p in range(16)]
                )
            )
            time.sleep(1)

    def gpio_event_detected(self, gpio_pin):

        pin_values = {}
        int_flag = self.mcp.int_flag
        int_cap = self.mcp.int_cap
        for mcp_pin in self.mcp_callbacks.keys():
            pin_values[mcp_pin] = [
                bool(int_cap[mcp_pin]),
                bool(self.mcp.get_pin(mcp_pin).value),
            ]

        logger.debug(
            f"GPIO interrupt on pin {gpio_pin} detected, flags and values are { pin_values }."
        )

        for mcp_pin in int_flag:
            mcp_pin_value = pin_values[mcp_pin]
            logger.info(f"mcp pin {mcp_pin} changed to: {mcp_pin_value}")

            if mcp_pin in self.mcp_callbacks:
                self.mcp_callbacks[mcp_pin](mcp_pin_value[0], pin_values)

    def close(self):
        GPIO_Module().cleanup()


if __name__ == "__main__":
    from resources.resources import init_logging

    init_logging()
    mcp_manager = MCPManager(i2c_manager=I2CManager(), executor=ThreadPoolExecutor())
    connected_pins = range(16)

    for pin in connected_pins:
        mcp_manager.add_callback(pin, lambda _: {})
    mcp_manager.setup()

    while True:
        time.sleep(1)
