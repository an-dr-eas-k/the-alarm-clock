import board
import busio
from adafruit_mcp230xx.mcp23017 import MCP23017
from utils.singleton import singleton


@singleton
class I2CManager:
    def __init__(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)


@singleton
class MCPManager:
    def __init__(self):
        self.mcp = MCP23017(I2CManager().i2c)
