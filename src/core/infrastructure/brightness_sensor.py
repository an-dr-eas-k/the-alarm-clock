import logging
import math
import threading
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


# BH1750 I2C addresses (ADDR pin low / high)
BH1750_I2C_ADDRESSES = (0x23, 0x5C)


class IBrightnessSensor:
    def get_room_brightness(self) -> float:
        raise NotImplementedError("Subclasses must implement get_room_brightness()")


class BH1750BrightnessSensor(IBrightnessSensor):
    def __init__(self, i2c_manager: I2CManager, address: int):
        self.sensor = None
        if i2c_manager.i2c is None:
            return
        try:
            self.sensor = adafruit_bh1750.BH1750(i2c_manager.i2c, address=address)
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
                logger.warning(
                    "photoresistor RC charge timed out after %.3fs "
                    "(check wiring on GPIO%d)",
                    CHARGE_TIMEOUT_SECONDS,
                    LIGHT_SENSOR_GPIO,
                )
                return CHARGE_TIMEOUT_SECONDS
        return time.perf_counter() - start

    def get_raw_charge_time(self) -> float:
        if self._gpio_module is None:
            logger.warning(
                "photoresistor: GPIO module unavailable, assuming brightest (%.6fs)",
                MIN_CHARGE_TIME_SECONDS,
            )
            return MIN_CHARGE_TIME_SECONDS
        try:
            charge_time = self._measure_charge_time_seconds()
            logger.debug("photoresistor raw RC charge time: %.6fs", charge_time)
            return charge_time
        except Exception:
            logger.warning(
                "photoresistor measurement failed, assuming brightest", exc_info=True
            )
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
        if clamped != charge_time:
            logger.debug(
                "photoresistor charge time %.6fs outside calibrated range "
                "[%.6f, %.6f], clamped to %.6fs",
                charge_time,
                MIN_CHARGE_TIME_SECONDS,
                MAX_CHARGE_TIME_SECONDS,
                clamped,
            )
        log_span = math.log(MAX_CHARGE_TIME_SECONDS) - math.log(MIN_CHARGE_TIME_SECONDS)
        normalized = (math.log(clamped) - math.log(MIN_CHARGE_TIME_SECONDS)) / log_span
        brightness = 1.0 - normalized
        logger.debug(
            "photoresistor charge time %.6fs -> brightness %.3f",
            charge_time,
            brightness,
        )
        return brightness


class CachedBrightnessSensor(IBrightnessSensor):
    """Measures the wrapped sensor continuously in a background thread and
    serves the most recent value from memory, so callers (e.g. the 250ms
    display refresh) never block on a slow or stalled measurement."""

    def __init__(self, sensor: IBrightnessSensor, interval_seconds: float = 0):
        self._sensor = sensor
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._value = self._measure(default=1.0)
        self._last_logged_value = self._value
        logger.info(
            "cached brightness sensor started (%s), initial brightness %.3f, "
            "interval %.3fs",
            type(sensor).__name__,
            self._value,
            interval_seconds,
        )
        self._thread = threading.Thread(
            target=self._run, name="brightness-sensor", daemon=True
        )
        self._thread.start()

    def _measure(self, default: float) -> float:
        try:
            return self._sensor.get_room_brightness()
        except Exception:
            logger.warning("brightness measurement failed", exc_info=True)
            return default

    def _run(self):
        while not self._stop_event.wait(self._interval_seconds):
            self._value = self._measure(default=self._value)
            # measurements run back-to-back, so only report meaningful changes
            if abs(self._value - self._last_logged_value) >= 0.05:
                logger.info(
                    "room brightness changed: %.3f -> %.3f",
                    self._last_logged_value,
                    self._value,
                )
                self._last_logged_value = self._value

    def get_room_brightness(self) -> float:
        return self._value

    def stop(self):
        logger.info("stopping cached brightness sensor")
        self._stop_event.set()


def _find_bh1750_address(i2c_manager: I2CManager) -> int | None:
    i2c = i2c_manager.i2c
    if i2c is None:
        return None
    try:
        while not i2c.try_lock():
            time.sleep(0.001)
        try:
            found = i2c.scan()
            return next((a for a in BH1750_I2C_ADDRESSES if a in found), None)
        finally:
            i2c.unlock()
    except Exception:
        logger.warning("I2C scan for brightness sensor failed", exc_info=True)
        return None


def create_brightness_sensor(i2c_manager: I2CManager) -> IBrightnessSensor:
    """Detect the connected brightness sensor: a BH1750 on the I2C bus if one
    answers, otherwise fall back to the GPIO photoresistor RC circuit (measured
    in the background and served from a cache)."""
    address = _find_bh1750_address(i2c_manager)
    if address is not None:
        logger.info(
            "BH1750 detected on I2C bus at 0x%02X, using it as brightness sensor",
            address,
        )
        return BH1750BrightnessSensor(i2c_manager, address)
    logger.info("no BH1750 detected, using photoresistor as brightness sensor")
    # the RC measurement takes milliseconds (up to the 0.5s timeout), so keep
    # it off the caller's thread; the BH1750 read is fast enough to stay direct
    return CachedBrightnessSensor(PhotoresistorBrightnessSensor())


if __name__ == "__main__":
    sensor = create_brightness_sensor(I2CManager())

    while True:
        print(
            "%s brightness: %.2f"
            % (type(sensor).__name__, sensor.get_room_brightness())
        )
        time.sleep(0.5)
