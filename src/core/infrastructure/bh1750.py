import logging
import time
from core.infrastructure.i2c_devices import I2CManager
import adafruit_bh1750

logger = logging.getLogger("tac.core.infrastructure.gpi")


class BrightnessSensor:
    def __init__(self, i2c_manager: I2CManager):
        self.i2c_manager = i2c_manager

    def get_room_brightness(self) -> float:
        try:
            i2c = self.i2c_manager.i2c
            sensor = adafruit_bh1750.BH1750(i2c)
            logger.debug("raw sensor value in lux: %s", sensor.lux)
            return sensor.lux
        except Exception:
            return 10000


if __name__ == "__main__":
    i2c_manager = I2CManager()
    sensor = BrightnessSensor(i2c_manager)

    while True:
        print("%.2f Lux" % sensor.get_room_brightness())
        time.sleep(1)
