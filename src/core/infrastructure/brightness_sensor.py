import logging
import time
import adafruit_bh1750

from core.infrastructure.i2c_devices import I2CManager

logger = logging.getLogger("tac.core.infrastructure.brightness")


class IBrightnessSensor:
    def get_room_brightness(self) -> float:
        raise NotImplementedError("Subclasses must implement get_room_brightness()")


class BrightnessSensor(IBrightnessSensor):
    def __init__(self, i2c_manager: I2CManager):
        self.sensor = adafruit_bh1750.BH1750(i2c_manager.i2c)

    def get_raw_lux(self) -> float:
        try:
            sensor_lux = self.sensor.lux
            logger.debug("raw sensor value in lux: %s", sensor_lux)
            return sensor_lux
        except Exception:
            return 10000

    def get_room_brightness(self) -> float:
        return min(self.get_raw_lux() / 25, 1.0)


if __name__ == "__main__":
    i2c_manager = I2CManager()
    sensor = BrightnessSensor(i2c_manager)

    while True:
        print("%.2f Lux" % sensor.get_room_brightness())
        time.sleep(1)
