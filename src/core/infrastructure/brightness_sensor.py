import logging
import time
import adafruit_bh1750

from core.infrastructure.i2c_devices import I2CManager

logger = logging.getLogger("tac.core.infrastructure.brightness")

# GPIO26 (BCM) wired to a photoresistor/capacitor RC divider:
# 3.3V -> photoresistor (GL5539) -> GPIO26 -> capacitor (103 = 10nF) -> GND
LIGHT_SENSOR_GPIO = 26

# Charge times (seconds) are inversely related to room brightness: more light
# lowers the photoresistor's resistance, so the capacitor charges faster.
# These bounds were picked for the 10nF cap + GL5539 pair and may need
# recalibrating against real readings (see __main__ below).
MIN_CHARGE_TIME_SECONDS = 0.00005
MAX_CHARGE_TIME_SECONDS = 0.02
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


class PhotoresistorBrightnessSensor(IBrightnessSensor):
    def __init__(self):
        self._gpio = None
        try:
            from RPi import GPIO

            GPIO.setmode(GPIO.BCM)
            self._gpio = GPIO
        except (ImportError, RuntimeError):
            logger.warning(
                "RPi.GPIO not available, brightness sensor disabled", exc_info=True
            )

    def _measure_charge_time_seconds(self) -> float:
        gpio = self._gpio
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
        if self._gpio is None:
            return MIN_CHARGE_TIME_SECONDS
        try:
            charge_time = self._measure_charge_time_seconds()
            logger.debug("raw RC charge time: %.6fs", charge_time)
            return charge_time
        except Exception:
            return MIN_CHARGE_TIME_SECONDS

    def get_room_brightness(self) -> float:
        charge_time = self.get_raw_charge_time()
        span = MAX_CHARGE_TIME_SECONDS - MIN_CHARGE_TIME_SECONDS
        normalized = (charge_time - MIN_CHARGE_TIME_SECONDS) / span
        return 1.0 - min(max(normalized, 0.0), 1.0)


if __name__ == "__main__":
    sensor = PhotoresistorBrightnessSensor()

    while True:
        print(
            "charge time: %.6fs, brightness: %.2f"
            % (sensor.get_raw_charge_time(), sensor.get_room_brightness())
        )
        time.sleep(0.5)
