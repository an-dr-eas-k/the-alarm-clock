import logging
from RPi import GPIO
import board
import busio
from digitalio import Direction, Pull
from adafruit_mcp230xx.mcp23017 import MCP23017
from utils.singleton import singleton

rotary_encoder_channel_a: int = 8
rotary_encoder_channel_b: int = 9
mode_button_channel: int = 0
invoke_button_channel: int = 1

interrupt_pin: int = 4


@singleton
class I2CManager:
    def __init__(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)


logger = logging.getLogger("tac.mcp")


@singleton
class MCPManager:

    def __init__(self):
        self.mcp = MCP23017(I2CManager().i2c)
        for i in range(0, 16):
            pin = mcp.get_pin(i)
            pin.direction = Direction.INPUT
            pin.pull = Pull.UP
            
        self.mcp.interrupt_enable = 0xC0E0 # only get interrupts for 1100000111000000 
        self.mcp.interrupt_configuration = 0xFFFF # only get notified, when any pin goes low
        self.mcp.io_control = 0x44
        self.mcp.default_value = 0xFFFF  # notify me, when any value gets low
        
        self.mcp.clear_ints()
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(interrupt_pin, GPIO.IN, GPIO.PUD_UP)
        GPIO.add_event_detect(
            interrupt_pin,
            GPIO.FALLING,
            callback=self.invoke_gpio_callback,
            bouncetime=10,
        )
        self.mcp_callbacks = {}

    def add_callback(self, pin_num, callback):
        self.mcp_callbacks[pin_num] = callback

    def invoke_gpio_callback(self, gpio_pin):
        logger.debug("interrupt occurred on gpio pin %s", gpio_pin)

        for mcp_pin in self.mcp.int_flag:
            mcp_pin_value = self.mcp.get_pin(mcp_pin).value
            if not mcp_pin_value:
                continue
            logger.debug(f"mcp pin {mcp_pin} changed to: {mcp_pin_value}")

            # if mcp_pin in self.mcp_callbacks:
            #     self.mcp_callbacks[mcp_pin]()

        self.mcp.clear_ints()

    def close(self):
        GPIO.cleanup()
