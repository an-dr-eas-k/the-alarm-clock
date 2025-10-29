import logging
import threading
import time
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


logger = logging.getLogger("tac.mcp")


class MCPManager:
    last_log_time = 0

    def __init__(self, i2c_manager: I2CManager):

        self.mcp = MCP23017(i2c_manager.i2c)
        for i in range(0, 16):
            pin = self.mcp.get_pin(i)
            pin.direction = Direction.INPUT
            pin.pull = Pull.UP

        self.mcp.interrupt_enable = 0xFFFF  # get interrupts for all pins
        self.mcp.interrupt_configuration = 0x0000  # notify me, when any value changes
        self.mcp.io_control = (
            0x44  # 0100 0100 # mirroring INT pins, open drain, active low
        )

        self.mcp.clear_ints()

        GPIO_Module().setmode(GPIO_Module().BCM)
        GPIO_Module().setup(interrupt_pin, GPIO_Module().IN, GPIO_Module().PUD_UP)
        GPIO_Module().add_event_detect(
            interrupt_pin,
            GPIO_Module().FALLING,
            callback=self.falling_gpio_event_detected,
        )
        GPIO_Module().add_event_detect(
            interrupt_pin,
            GPIO_Module().RISING,
            callback=self.raising_gpio_event_detected,
        )
        self.mcp_callbacks = {}

        if logger.level == logging.DEBUG:
            self.log_thread = threading.Thread(target=self._log_thread_callback)
            self.log_thread.daemon = True
            self.log_thread.start()

    def add_callback(self, pin_num, callback):
        self.mcp_callbacks[pin_num] = callback

    def _log_thread_callback(self):
        while True:
            current_time = time.time()
            if self.last_log_time < current_time - 1:
                self.last_log_time = current_time
                logger.debug(
                    f"interrupt state: {int(GPIO_Module.input(interrupt_pin))}, mcp pin states: "
                    + ", ".join(
                        [f"{p:02}: {int(self.mcp.get_pin(p).value)}" for p in range(16)]
                    )
                )

    def raising_gpio_event_detected(self, gpio_pin):
        self.gpio_event_detected(gpio_pin, False)

    def falling_gpio_event_detected(self, gpio_pin):
        self.gpio_event_detected(gpio_pin, True)

    def gpio_event_detected(self, gpio_pin, is_falling: bool):
        logger.debug(
            f"GPIO interrupt on pin {gpio_pin} detected: {'FALLING' if is_falling else 'RISING'}."
        )

        for mcp_pin in self.mcp.int_flag:
            mcp_pin_value = self.mcp.get_pin(mcp_pin).value
            if mcp_pin_value != is_falling:
                return
            logger.debug(f"mcp pin {mcp_pin} changed to: {mcp_pin_value}")

            if mcp_pin in self.mcp_callbacks:
                self.mcp_callbacks[mcp_pin](mcp_pin, mcp_pin_value)

        self.mcp.clear_ints()

    def close(self):
        GPIO_Module().cleanup()


if __name__ == "__main__":

    i2c = I2CManager().i2c

    mcp = MCP23017(i2c)
    connected_pins = [0, 1, 8, 9, 10]
    for i in connected_pins:
        pin = mcp.get_pin(i)
        pin.direction = Direction.INPUT
        pin.pull = Pull.UP

    while True:
        for i in connected_pins:
            pin = mcp.get_pin(i)
            print(f"Pin {i} is at level: {pin.value}")

        print("-----")
        time.sleep(1)
