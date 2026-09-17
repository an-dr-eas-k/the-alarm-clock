import logging
import math
import time
import adafruit_bh1750

from core.infrastructure.i2c_devices import I2CManager
from core.infrastructure.rpi_gpio import GPIODeviceBase

logger = logging.getLogger("tac.core.infrastructure.brightness")

# GPIO26 (BCM) wired to a photoresistor/capacitor RC divider:
# 3.3V -> photoresistor (GL5539) -> GPIO26 -> capacitor (103 = 10nF) -> GND
LIGHT_SENSOR_GPIO = 26

# Charge times (seconds) are inversely related to room brightness: more light
# lowers the photoresistor's resistance, so the capacitor charges faster.
# Calibrated from field readings on the 10nF cap + GL5539 pair (~250us in a lit
# room, ~5ms with the sensor covered); recalibrate further with __main__ below
# if your bright/dark extremes differ.
MIN_CHARGE_TIME_SECONDS = 0.00015
MAX_CHARGE_TIME_SECONDS = 0.007
CHARGE_TIMEOUT_SECONDS = 0.5


class IBrightnessSensor:
    def get_room_brightness(self) -> float:
        raise NotImplementedError("Subclasses must implement get_room_brightness()")


class BH1750BrightnessSensor(IBrightnessSensor):
    def __init__(self, i2c_manager: I2CManager):
        self.sensor = None
        if i2c_manager.i2c is None:
            return
        try:
            self.sensor = adafruit_bh1750.BH1750(i2c_manager.i2c)
        except Exception:
            logger.warning(
                "failed to initialize BH1750 brightness sensor", exc_info=True
            )

    def get_raw_lux(self) -> float:
        if self.sensor is None:
            return 10000
        try:
            sensor_lux = self.sensor.lux
            logger.debug("raw sensor value in lux: %s", sensor_lux)
            return sensor_lux
        except Exception:
            return 10000

    def get_room_brightness(self) -> float:
        return min(self.get_raw_lux() / 25, 1.0)


class PhotoresistorBrightnessSensor(IBrightnessSensor, GPIODeviceBase):
    def _measure_charge_time_seconds(self) -> float:
        gpio = self._gpio_module
        # fully discharge the capacitor before timing how long it takes to charge
        gpio.setup(LIGHT_SENSOR_GPIO, gpio.OUT)
        gpio.output(LIGHT_SENSOR_GPIO, gpio.LOW)
        time.sleep(0.01)

        gpio.setup(LIGHT_SENSOR_GPIO, gpio.IN, pull_up_down=gpio.PUD_OFF)
        start = time.perf_counter()
        while not gpio.input(LIGHT_SENSOR_GPIO):
            if time.perf_counter() - start > CHARGE_TIMEOUT_SECONDS:
                return CHARGE_TIMEOUT_SECONDS
        return time.perf_counter() - start

    def get_raw_charge_time(self) -> float:
        if self._gpio_module is None:
            return MIN_CHARGE_TIME_SECONDS
        try:
            charge_time = self._measure_charge_time_seconds()
            logger.debug("raw RC charge time: %.6fs", charge_time)
            return charge_time
        except Exception:
            return MIN_CHARGE_TIME_SECONDS

    def get_room_brightness(self) -> float:
        charge_time = self.get_raw_charge_time()
        # photoresistor resistance (and thus charge time) scales roughly as a
        # power of illuminance, so most everyday brightness levels sit close to
        # MIN_CHARGE_TIME_SECONDS; compare on a log scale instead of linearly to
        # avoid compressing them all into a narrow band near 1.0
        clamped = min(
            max(charge_time, MIN_CHARGE_TIME_SECONDS), MAX_CHARGE_TIME_SECONDS
        )
        log_span = math.log(MAX_CHARGE_TIME_SECONDS) - math.log(MIN_CHARGE_TIME_SECONDS)
        normalized = (math.log(clamped) - math.log(MIN_CHARGE_TIME_SECONDS)) / log_span
        return 1.0 - normalized


if __name__ == "__main__":
    sensor = PhotoresistorBrightnessSensor()

    while True:
        print(
            "charge time: %.6fs, brightness: %.2f"
            % (sensor.get_raw_charge_time(), sensor.get_room_brightness())
        )
        time.sleep(0.5)
