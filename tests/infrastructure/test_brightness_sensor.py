import math
import unittest
from unittest import mock

from core.infrastructure import brightness_sensor
from core.infrastructure.brightness_sensor import (
    CHARGE_TIMEOUT_SECONDS,
    LIGHT_SENSOR_GPIO,
    MAX_CHARGE_TIME_SECONDS,
    MIN_CHARGE_TIME_SECONDS,
    BH1750BrightnessSensor,
    IBrightnessSensor,
    PhotoresistorBrightnessSensor,
)


class TestInterface(unittest.TestCase):
    def test_interface_method_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            IBrightnessSensor().get_room_brightness()


class TestBH1750BrightnessSensor(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(brightness_sensor, "adafruit_bh1750")
        self.bh1750_module = patcher.start()
        self.addCleanup(patcher.stop)
        self.i2c_manager = mock.Mock(i2c=mock.Mock(name="i2c"))

    def _sensor_with_lux(self, lux):
        sensor = BH1750BrightnessSensor(self.i2c_manager)
        sensor.sensor = mock.Mock(lux=lux)
        return sensor

    def test_initializes_sensor_on_i2c_bus(self):
        sensor = BH1750BrightnessSensor(self.i2c_manager)

        self.bh1750_module.BH1750.assert_called_once_with(self.i2c_manager.i2c)
        self.assertIs(self.bh1750_module.BH1750.return_value, sensor.sensor)

    def test_without_i2c_bus_sensor_is_disabled(self):
        self.i2c_manager.i2c = None

        sensor = BH1750BrightnessSensor(self.i2c_manager)

        self.assertIsNone(sensor.sensor)
        self.bh1750_module.BH1750.assert_not_called()

    def test_init_failure_is_logged_and_disables_sensor(self):
        self.bh1750_module.BH1750.side_effect = OSError("no device at 0x23")

        with self.assertLogs("tac.core.infrastructure.brightness", "WARNING"):
            sensor = BH1750BrightnessSensor(self.i2c_manager)

        self.assertIsNone(sensor.sensor)

    def test_raw_lux_reads_sensor(self):
        self.assertEqual(123.5, self._sensor_with_lux(123.5).get_raw_lux())

    def test_raw_lux_defaults_to_bright_without_sensor(self):
        self.i2c_manager.i2c = None

        self.assertEqual(10000, BH1750BrightnessSensor(self.i2c_manager).get_raw_lux())

    def test_raw_lux_defaults_to_bright_when_read_fails(self):
        sensor = BH1750BrightnessSensor(self.i2c_manager)
        sensor.sensor = mock.Mock()
        type(sensor.sensor).lux = mock.PropertyMock(side_effect=OSError("i2c"))

        self.assertEqual(10000, sensor.get_raw_lux())

    def test_room_brightness_scales_lux_linearly_up_to_25_lux(self):
        self.assertAlmostEqual(0.4, self._sensor_with_lux(10).get_room_brightness())

    def test_room_brightness_is_capped_at_one(self):
        self.assertEqual(1.0, self._sensor_with_lux(5000).get_room_brightness())

    def test_room_brightness_is_zero_in_darkness(self):
        self.assertEqual(0, self._sensor_with_lux(0).get_room_brightness())

    def test_room_brightness_without_sensor_is_full(self):
        self.i2c_manager.i2c = None

        self.assertEqual(
            1.0, BH1750BrightnessSensor(self.i2c_manager).get_room_brightness()
        )


class TestPhotoresistorBrightnessSensor(unittest.TestCase):
    def setUp(self):
        self.sensor = PhotoresistorBrightnessSensor()
        self.gpio = mock.MagicMock(name="GPIO")
        self.gpio.OUT, self.gpio.IN = "OUT", "IN"
        self.gpio.LOW, self.gpio.PUD_OFF = "LOW", "PUD_OFF"
        self.sensor._gpio_module_cache = self.gpio
        time_patcher = mock.patch.object(brightness_sensor, "time")
        self.time = time_patcher.start()
        self.addCleanup(time_patcher.stop)

    def _without_gpio(self):
        return mock.patch.object(PhotoresistorBrightnessSensor, "_gpio_module", None)

    def test_raw_charge_time_without_gpio_is_minimum(self):
        with self._without_gpio():
            self.assertEqual(MIN_CHARGE_TIME_SECONDS, self.sensor.get_raw_charge_time())

    def test_measurement_discharges_capacitor_then_times_charge(self):
        self.gpio.input.side_effect = [0, 0, 1]
        self.time.perf_counter.side_effect = [10.0, 10.0001, 10.0002, 10.0003]

        charge_time = self.sensor._measure_charge_time_seconds()

        self.assertAlmostEqual(0.0003, charge_time)
        self.gpio.setup.assert_has_calls(
            [
                mock.call(LIGHT_SENSOR_GPIO, "OUT"),
                mock.call(LIGHT_SENSOR_GPIO, "IN", pull_up_down="PUD_OFF"),
            ]
        )
        self.gpio.output.assert_called_once_with(LIGHT_SENSOR_GPIO, "LOW")
        self.time.sleep.assert_called_once_with(0.01)

    def test_measurement_times_out_when_pin_never_goes_high(self):
        self.gpio.input.return_value = 0
        self.time.perf_counter.side_effect = [0.0, 0.1, CHARGE_TIMEOUT_SECONDS + 0.1]

        self.assertEqual(
            CHARGE_TIMEOUT_SECONDS, self.sensor._measure_charge_time_seconds()
        )

    def test_raw_charge_time_returns_measurement(self):
        with mock.patch.object(
            self.sensor, "_measure_charge_time_seconds", return_value=0.002
        ):
            self.assertEqual(0.002, self.sensor.get_raw_charge_time())

    def test_raw_charge_time_falls_back_to_minimum_on_gpio_error(self):
        with mock.patch.object(
            self.sensor, "_measure_charge_time_seconds", side_effect=RuntimeError
        ):
            self.assertEqual(MIN_CHARGE_TIME_SECONDS, self.sensor.get_raw_charge_time())

    def _brightness_for(self, charge_time):
        with mock.patch.object(
            self.sensor, "get_raw_charge_time", return_value=charge_time
        ):
            return self.sensor.get_room_brightness()

    def test_fastest_charge_time_is_fully_bright(self):
        self.assertAlmostEqual(1.0, self._brightness_for(MIN_CHARGE_TIME_SECONDS))

    def test_slowest_charge_time_is_dark(self):
        self.assertAlmostEqual(0.0, self._brightness_for(MAX_CHARGE_TIME_SECONDS))

    def test_charge_time_below_minimum_is_clamped_to_fully_bright(self):
        self.assertAlmostEqual(1.0, self._brightness_for(0.00001))

    def test_charge_time_above_maximum_is_clamped_to_dark(self):
        self.assertAlmostEqual(0.0, self._brightness_for(CHARGE_TIMEOUT_SECONDS))

    def test_geometric_mean_charge_time_is_half_bright(self):
        mid = math.sqrt(MIN_CHARGE_TIME_SECONDS * MAX_CHARGE_TIME_SECONDS)

        self.assertAlmostEqual(0.5, self._brightness_for(mid))

    def test_brightness_decreases_monotonically_with_charge_time(self):
        times = [0.0002, 0.0005, 0.001, 0.003, 0.006]

        values = [self._brightness_for(t) for t in times]

        self.assertEqual(sorted(values, reverse=True), values)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in values))

    def test_brightness_without_gpio_is_full(self):
        with self._without_gpio():
            self.assertAlmostEqual(1.0, self.sensor.get_room_brightness())


if __name__ == "__main__":
    unittest.main()
