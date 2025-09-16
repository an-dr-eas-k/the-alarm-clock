import logging
from RPi import GPIO
import board
import busio
from adafruit_mcp230xx.mcp23017 import MCP23017
from utils.singleton import singleton


@singleton
class I2CManager:
    def __init__(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)


logger = logging.getLogger("tac.mcp")


@singleton
class MCPManager:
    rotary_encoder_channel_a: int = 8
    rotary_encoder_channel_b: int = 9
    mode_button_pin: int = 0
    invoke_button_pin: int = 1

    def __init__(self):
        self.mcp = MCP23017(I2CManager().i2c)
        self.mcp.interrupt_enable = 0xFFFF
        self.mcp.interrupt_configuration = 0x0000
        self.mcp.io_control = 0x44
        self.mcp.clear_ints()
        GPIO.setmode(GPIO.BCM)
        interrupt = 17
        GPIO.setup(interrupt, GPIO.IN, GPIO.PUD_UP)
        GPIO.add_event_detect(
            interrupt, GPIO.FALLING, callback=self.invoke_pin_callback, bouncetime=10
        )
        self.pin_callbacks = {}

    def add_callback(self, pin_num, callback):
        self.pin_callbacks[pin_num] = callback

    def invoke_pin_callback(self, pin):
        logger.debug("interrupt occurred on mcp pin %s", pin)
        if pin in self.pin_callbacks:
            self.pin_callbacks[pin]()

    def close(self):
        GPIO.cleanup()
