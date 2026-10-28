import unittest
from unittest import mock

import alsaaudio

from utils import sound_device
from utils.sound_device import Algorithm, SoundDevice, TACSoundDevice


class FakeMixer:
    """Minimal stand-in for alsaaudio.Mixer with separate dB/raw scales."""

    def __init__(self, db_range=(-10000, 0), db_volume=(-3000, -3000),
                 raw_range=(0, 100), raw_volume=(50, 50)):
        self.ranges = {
            alsaaudio.VOLUME_UNITS_DB: list(db_range),
            alsaaudio.VOLUME_UNITS_RAW: list(raw_range),
        }
        self.volumes = {
            alsaaudio.VOLUME_UNITS_DB: list(db_volume),
            alsaaudio.VOLUME_UNITS_RAW: list(raw_volume),
        }
        self.set_calls = []
        self.closed = False

    def getrange(self, units=None):
        return self.ranges[units]

    def getvolume(self, units=None):
        return self.volumes[units]

    def setvolume(self, value, channel=None, units=None):
        self.set_calls.append((value, channel, units))

    def cardname(self):
        return "FakeCard"

    def mixer(self):
        return "Master"

    def close(self):
        self.closed = True


def device_with_mixer(mixer, control="Master"):
    device = SoundDevice(control=control)
    patcher = mock.patch.object(device, "get_mixer", return_value=mixer)
    patcher.start()
    return device, patcher


class VolumeConversionTest(unittest.TestCase):
    def setUp(self):
        self.device = SoundDevice()

    def test_combine_channel_values_averages(self):
        self.assertEqual(self.device.combine_channel_values([10, 20, 30]), 20)

    def test_combine_channel_values_single_channel(self):
        self.assertEqual(self.device.combine_channel_values([42]), 42)

    def test_combine_channel_values_empty_is_zero(self):
        self.assertEqual(self.device.combine_channel_values([]), 0)

    def test_human_volume_at_max_is_one(self):
        self.assertAlmostEqual(self.device.convert_to_human_volume(0, 0), 1.0)

    def test_human_volume_drops_tenfold_every_60_db(self):
        self.assertAlmostEqual(
            self.device.convert_to_human_volume(-6000, 0), 0.1
        )

    def test_human_volume_above_max_returns_max_volume(self):
        self.assertEqual(self.device.convert_to_human_volume(500, 100), 100)

    def test_normalized_volume(self):
        self.assertEqual(self.device.convert_to_normalized_volume(50, 0, 100), 0.5)
        self.assertEqual(self.device.convert_to_normalized_volume(15, 10, 20), 0.5)

    def test_normalized_volume_with_empty_range_raises(self):
        with self.assertRaises(ZeroDivisionError):
            self.device.convert_to_normalized_volume(5, 5, 5)

    def test_from_human_volume_is_inverse_of_to_human_volume(self):
        db = self.device.convert_from_human_volume(0.1, -10000, 0)
        self.assertAlmostEqual(db, -6000)
        self.assertAlmostEqual(self.device.convert_to_human_volume(db, 0), 0.1)

    def test_from_human_volume_clamps_to_max(self):
        self.assertEqual(self.device.convert_from_human_volume(5.0, -10000, 0), 0)

    def test_from_human_volume_clamps_to_min(self):
        self.assertEqual(self.device.convert_from_human_volume(1e-9, -10000, 0), -10000)

    def test_from_human_volume_zero_returns_min(self):
        self.assertEqual(self.device.convert_from_human_volume(0, -10000, 0), -10000)

    def test_from_human_volume_negative_returns_min(self):
        self.assertEqual(self.device.convert_from_human_volume(-1, -10000, 0), -10000)

    def test_from_normalized_volume_interpolates(self):
        self.assertEqual(self.device.convert_from_normalized_volume(0.5, 0, 100), 50)
        self.assertEqual(self.device.convert_from_normalized_volume(0.5, 10, 20), 15)

    def test_from_normalized_volume_clamps(self):
        self.assertEqual(self.device.convert_from_normalized_volume(-1, 0, 100), 0)
        self.assertEqual(self.device.convert_from_normalized_volume(2, 0, 100), 100)


class InvokeOnMixerTest(unittest.TestCase):
    def test_without_control_callback_is_skipped(self):
        device = SoundDevice(control=None)
        callback = mock.Mock()
        with mock.patch.object(device, "get_mixer") as get_mixer, self.assertLogs(
            "tac.sound_device", "WARNING"
        ):
            self.assertIsNone(device.invoke_on_mixer(callback))
        callback.assert_not_called()
        get_mixer.assert_not_called()

    def test_mixer_open_failure_returns_none(self):
        device = SoundDevice(control="Master")
        callback = mock.Mock()
        with mock.patch.object(
            device, "get_mixer", side_effect=alsaaudio.ALSAAudioError("nope")
        ), self.assertLogs("tac.sound_device", "WARNING"):
            self.assertIsNone(device.invoke_on_mixer(callback))
        callback.assert_not_called()

    def test_returns_callback_result_and_closes_mixer(self):
        mixer = FakeMixer()
        device, patcher = device_with_mixer(mixer)
        self.addCleanup(patcher.stop)

        self.assertEqual(device.invoke_on_mixer(lambda m: m.cardname()), "FakeCard")
        self.assertTrue(mixer.closed)

    def test_opens_mixer_with_configured_control_and_device(self):
        mixer = FakeMixer()
        device = SoundDevice(control="Digital", device="hw:1")
        with mock.patch.object(device, "get_mixer", return_value=mixer) as get_mixer:
            device.invoke_on_mixer(lambda m: None)
        get_mixer.assert_called_once_with(control="Digital", device="hw:1")

    def test_mixer_is_closed_when_callback_raises(self):
        mixer = FakeMixer()
        device, patcher = device_with_mixer(mixer)
        self.addCleanup(patcher.stop)

        def failing(_):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            device.invoke_on_mixer(failing)
        self.assertTrue(mixer.closed)

    def test_none_callback_returns_none_and_closes_mixer(self):
        mixer = FakeMixer()
        device, patcher = device_with_mixer(mixer)
        self.addCleanup(patcher.stop)

        self.assertIsNone(device.invoke_on_mixer(None))
        self.assertTrue(mixer.closed)


class GetAlgorithmTest(unittest.TestCase):
    def test_cubic_when_volume_below_max_db(self):
        algorithm = SoundDevice().get_algorithm(FakeMixer(db_volume=(-3000, -1000)))
        self.assertEqual(algorithm, Algorithm("cubic", -2000, -10000, 0))

    def test_linear_when_volume_at_max_db(self):
        algorithm = SoundDevice().get_algorithm(FakeMixer(db_volume=(0, 0)))
        self.assertEqual(algorithm.name, "linear")

    def test_linear_when_db_range_is_degenerate(self):
        mixer = FakeMixer(db_range=(0, 0), db_volume=(0, 0))
        self.assertEqual(SoundDevice().get_algorithm(mixer).name, "linear")


class SystemVolumeTest(unittest.TestCase):
    def tearDown(self):
        for patcher in getattr(self, "patchers", []):
            patcher.stop()

    def device_for(self, mixer):
        device, patcher = device_with_mixer(mixer)
        self.patchers = [patcher]
        return device

    def test_get_volume_cubic(self):
        device = self.device_for(FakeMixer(db_volume=(-6000, -6000)))
        self.assertAlmostEqual(device.get_system_volume(), 0.1)

    def test_get_volume_linear(self):
        mixer = FakeMixer(db_volume=(0, 0), raw_range=(0, 200), raw_volume=(50, 50))
        self.assertAlmostEqual(self.device_for(mixer).get_system_volume(), 0.25)

    def test_get_volume_without_mixer_is_zero(self):
        with self.assertLogs("tac.sound_device", "WARNING"):
            self.assertEqual(SoundDevice(control=None).get_system_volume(), 0.0)

    def test_get_volume_when_mixer_unavailable_is_zero(self):
        device = SoundDevice(control="Master")
        with mock.patch.object(
            device, "get_mixer", side_effect=alsaaudio.ALSAAudioError("x")
        ), self.assertLogs("tac.sound_device", "WARNING"):
            self.assertEqual(device.get_system_volume(), 0.0)

    def test_set_volume_cubic_uses_db_units(self):
        mixer = FakeMixer(db_volume=(-3000, -3000))
        self.device_for(mixer).set_system_volume(0.1)
        self.assertEqual(mixer.set_calls, [(-6000, None, alsaaudio.VOLUME_UNITS_DB)])

    def test_set_volume_linear_uses_raw_units(self):
        mixer = FakeMixer(db_volume=(0, 0), raw_range=(0, 200))
        self.device_for(mixer).set_system_volume(0.5)
        self.assertEqual(mixer.set_calls, [(100, None, alsaaudio.VOLUME_UNITS_RAW)])

    def test_set_volume_above_one_is_clamped_to_max(self):
        mixer = FakeMixer(db_volume=(-3000, -3000))
        self.device_for(mixer).set_system_volume(5)
        self.assertEqual(mixer.set_calls, [(0, None, alsaaudio.VOLUME_UNITS_DB)])

    def test_set_volume_zero_is_clamped_to_min(self):
        mixer = FakeMixer(db_volume=(-3000, -3000))
        self.device_for(mixer).set_system_volume(0)
        self.assertEqual(mixer.set_calls, [(-10000, None, alsaaudio.VOLUME_UNITS_DB)])

    def test_set_volume_without_mixer_does_nothing(self):
        with self.assertLogs("tac.sound_device", "WARNING"):
            SoundDevice(control=None).set_system_volume(0.5)

    def test_set_then_mixer_is_closed(self):
        mixer = FakeMixer()
        self.device_for(mixer).set_system_volume(0.5)
        self.assertTrue(mixer.closed)


class ControlsSettingsTest(unittest.TestCase):
    def test_get_controls_settings_collects_volume_per_control(self):
        mixers = {"Master": FakeMixer(), "PCM": FakeMixer()}
        mixers["Master"].getvolume = mock.Mock(return_value=[30, 30])
        mixers["PCM"].getvolume = mock.Mock(return_value=[80])
        device = SoundDevice(device="hw:0")

        with mock.patch.object(
            sound_device.alsaaudio, "mixers", return_value=["Master", "PCM"]
        ) as list_mixers, mock.patch.object(
            device, "get_mixer", side_effect=lambda control, device: mixers[control]
        ):
            settings = device.get_controls_settings()

        list_mixers.assert_called_once_with(device="hw:0")
        self.assertEqual(settings, {"Master": [30, 30], "PCM": [80]})
        self.assertTrue(all(m.closed for m in mixers.values()))

    def test_get_controls_settings_without_controls_is_empty(self):
        with mock.patch.object(sound_device.alsaaudio, "mixers", return_value=[]):
            self.assertEqual(SoundDevice().get_controls_settings(), {})

    def test_set_controls_settings_sets_each_channel(self):
        mixers = {"Master": FakeMixer(), "PCM": FakeMixer()}
        device = SoundDevice()
        with mock.patch.object(
            device, "get_mixer", side_effect=lambda control, device: mixers[control]
        ):
            device.set_controls_settings({"Master": [10, 20], "PCM": [70]})

        self.assertEqual(mixers["Master"].set_calls, [(10, 0, None), (20, 1, None)])
        self.assertEqual(mixers["PCM"].set_calls, [(70, 0, None)])
        self.assertTrue(all(m.closed for m in mixers.values()))

    def test_set_controls_settings_with_empty_settings_does_nothing(self):
        device = SoundDevice()
        with mock.patch.object(device, "get_mixer") as get_mixer:
            device.set_controls_settings({})
        get_mixer.assert_not_called()


class DebugInfoTest(unittest.TestCase):
    def test_logs_cards_and_mixers_per_pcm(self):
        with mock.patch.object(
            sound_device.alsaaudio, "cards", return_value=["card0"]
        ), mock.patch.object(
            sound_device.alsaaudio, "pcms", return_value=["default", "hw:0"]
        ), mock.patch.object(
            sound_device.alsaaudio, "mixers", return_value=["Master"]
        ), self.assertLogs("tac.sound_device", "INFO") as logs:
            SoundDevice().debug_info()

        output = "\n".join(logs.output)
        self.assertIn("card0", output)
        self.assertIn("pcm default mixers: Master", output)
        self.assertIn("pcm hw:0 mixers: Master", output)

    def test_mixer_listing_errors_are_swallowed(self):
        with mock.patch.object(
            sound_device.alsaaudio, "cards", return_value=[]
        ), mock.patch.object(
            sound_device.alsaaudio, "pcms", return_value=["broken"]
        ), mock.patch.object(
            sound_device.alsaaudio, "mixers", side_effect=alsaaudio.ALSAAudioError("x")
        ):
            SoundDevice().debug_info()


class TACSoundDeviceTest(unittest.TestCase):
    def setUp(self):
        for name, value in (("cards", []), ("pcms", [])):
            patcher = mock.patch.object(
                sound_device.alsaaudio, name, return_value=value
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def build(self, available):
        opened = []

        def fake_get_mixer(self_, control, device):
            opened.append(control)
            if control not in available:
                raise alsaaudio.ALSAAudioError("no such control")
            return FakeMixer()

        with mock.patch.object(TACSoundDevice, "get_mixer", fake_get_mixer):
            device = TACSoundDevice()
        return device, opened

    def test_first_valid_control_is_selected(self):
        device, opened = self.build({"Digital", "Master"})
        self.assertEqual(device.control, "Digital")
        self.assertEqual(opened, ["Digital"])

    def test_falls_back_to_next_control(self):
        device, opened = self.build({"Master"})
        self.assertEqual(device.control, "Master")
        self.assertEqual(opened, ["Digital", "Master"])

    def test_no_valid_control_leaves_device_disabled(self):
        with self.assertLogs("tac.sound_device", "WARNING"):
            device, _ = self.build(set())
        self.assertIsNone(device.control)
        with self.assertLogs("tac.sound_device", "WARNING"):
            self.assertEqual(device.get_system_volume(), 0.0)

    def test_init_mixer_uses_given_device_and_candidates(self):
        device, _ = self.build({"Master"})
        with mock.patch.object(device, "get_mixer", return_value=FakeMixer()) as get_mixer:
            device.init_mixer(["Custom"], device="hw:2")
        get_mixer.assert_called_once_with(control="Custom", device="hw:2")
        self.assertEqual((device.control, device.device), ("Custom", "hw:2"))

    def test_lock_is_released_after_init(self):
        device, _ = self.build({"Master"})
        self.assertTrue(device.threadLock.acquire(False))
        device.threadLock.release()


class GetMixerTest(unittest.TestCase):
    def test_get_mixer_delegates_to_alsaaudio(self):
        with mock.patch.object(sound_device.alsaaudio, "Mixer") as mixer_class:
            result = SoundDevice().get_mixer(control="PCM", device="hw:1")
        mixer_class.assert_called_once_with(control="PCM", device="hw:1")
        self.assertIs(result, mixer_class.return_value)


if __name__ == "__main__":
    unittest.main()
