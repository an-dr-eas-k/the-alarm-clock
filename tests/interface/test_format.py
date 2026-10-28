import datetime
import unittest
from unittest import mock

from PIL import Image

from core.domain.mode_coordinator import ModeName
from core.domain.model import Mode, RoomBrightness
from core.interface.display.format import ColorType
from tests.interface.display_helpers import (
    DisplayEnvironment,
    make_coordinator,
    next_alarm_info_at,
)
from tests.support import frozen_now, local_datetime
from utils.drawing import PresentationFont


class ColorConversionTest(unittest.TestCase):
    def setUp(self):
        self.formatter = DisplayEnvironment().formatter

    def test_16_level_value_is_returned_as_is(self):
        self.assertEqual(
            9, self.formatter._color(9, color_type=ColorType.IN16)
        )

    def test_256_level_scales_by_sixteen(self):
        self.assertEqual(
            144, self.formatter._color(9, color_type=ColorType.IN256)
        )

    def test_rgb_int_replicates_gray_into_all_channels(self):
        self.assertEqual(
            0x909090, self.formatter._color(9, color_type=ColorType.INCOLOR)
        )

    def test_hex_scales_to_full_range(self):
        self.assertEqual("#000000", self.formatter._color(0, color_type=ColorType.INHEX))
        self.assertEqual("#ffffff", self.formatter._color(15, color_type=ColorType.INHEX))
        self.assertEqual("#111111", self.formatter._color(1, color_type=ColorType.INHEX))

    def test_values_are_clamped_to_range(self):
        self.assertEqual(15, self.formatter._color(99, color_type=ColorType.IN16))
        self.assertEqual(0, self.formatter._color(-4, color_type=ColorType.IN16))
        self.assertEqual(
            4, self.formatter._color(1, min_value=4, color_type=ColorType.IN16)
        )

    def test_foreground_color_respects_minimum(self):
        self.formatter._foreground_grayscale_16 = 0

        self.assertEqual(1, self.formatter.foreground_color(color_type=ColorType.IN16))
        self.assertEqual(
            5,
            self.formatter.foreground_color(min_value=5, color_type=ColorType.IN16),
        )

    def test_background_color_uses_background_level(self):
        self.formatter._background_grayscale_16 = 7

        self.assertEqual(7, self.formatter.background_color(ColorType.IN16))
        self.assertEqual(0x707070, self.formatter.background_color())


class BeGloomyTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment(brightness=0.0)
        self.now = local_datetime(2026, 3, 1, 6, 0)

    def test_dark_idle_room_is_gloomy(self):
        self.assertTrue(self.env.formatter.be_gloomy())

    def test_lit_room_is_not_gloomy(self):
        self.env.content.room_brightness = RoomBrightness(0.5)
        self.assertFalse(self.env.formatter.be_gloomy())

    def test_volume_meter_prevents_gloom(self):
        self.env.content.show_volume_meter = True
        self.assertFalse(self.env.formatter.be_gloomy())

    def test_active_playback_prevents_gloom(self):
        self.env.playback.playback_mode = Mode.Music
        self.assertFalse(self.env.formatter.be_gloomy())

    def test_menu_mode_prevents_gloom(self):
        self.env.context.mode_coordinator = make_coordinator(ModeName.ALARM_EDIT)
        self.assertFalse(self.env.formatter.be_gloomy())

    def test_default_mode_coordinator_still_gloomy(self):
        self.env.context.mode_coordinator = make_coordinator(ModeName.DEFAULT)
        self.assertTrue(self.env.formatter.be_gloomy())

    def test_active_visual_effect_prevents_gloom(self):
        with frozen_now(self.now):
            self.env.content.update_next_alarm(
                next_alarm_info_at(
                    self.now + datetime.timedelta(minutes=5), with_visual_effect=True
                )
            )
            self.assertFalse(self.env.formatter.be_gloomy())

    def test_distant_visual_effect_still_gloomy(self):
        with frozen_now(self.now):
            self.env.content.update_next_alarm(
                next_alarm_info_at(
                    self.now + datetime.timedelta(hours=3), with_visual_effect=True
                )
            )
            self.assertTrue(self.env.formatter.be_gloomy())


class FontSelectionTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment(brightness=1.0)
        patcher = mock.patch.object(
            PresentationFont, "get_font_family", side_effect=lambda *a: a
        )
        self.get_font_family = patcher.start()
        self.addCleanup(patcher.stop)

    def test_clock_font_is_roboto_when_lit(self):
        path, size, _ = self.env.formatter.clock_font(size=30)

        self.assertEqual(PresentationFont.roboto_font, path)
        self.assertEqual(30, size)

    def test_clock_and_info_font_switch_to_light_font_when_gloomy(self):
        self.env.content.room_brightness = RoomBrightness(0.0)

        self.assertEqual(
            PresentationFont.light_clock_font, self.env.formatter.clock_font()[0]
        )
        self.assertEqual(
            PresentationFont.light_clock_font, self.env.formatter.info_font()[0]
        )

    def test_icon_and_weather_fonts_ignore_gloom(self):
        self.env.content.room_brightness = RoomBrightness(0.0)

        self.assertEqual(
            PresentationFont.roboto_font, self.env.formatter.icon_font()[0]
        )
        self.assertEqual(
            PresentationFont.weather_font, self.env.formatter.weather_font()[0]
        )

    def test_default_sizes(self):
        self.assertEqual(20, self.env.formatter.clock_font()[1])
        self.assertEqual(18, self.env.formatter.info_font()[1])
        self.assertEqual(18, self.env.formatter.icon_font()[1])
        self.assertEqual(18, self.env.formatter.weather_font()[1])


class AdjustDisplayTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment()
        self.formatter = self.env.formatter
        self.now = local_datetime(2026, 3, 1, 6, 0)

    def adjust(self, brightness):
        self.env.content.room_brightness = RoomBrightness(brightness)
        self.formatter.adjust_display()
        return (
            self.formatter.foreground_color(color_type=ColorType.IN16),
            self.formatter.background_color(ColorType.IN16),
        )

    def test_bright_room_uses_full_foreground(self):
        self.assertEqual((15, 0), self.adjust(1.0))

    def test_foreground_levels_follow_room_brightness(self):
        self.assertEqual(10, self.adjust(0.1)[0])
        self.assertEqual(7, self.adjust(0.04)[0])
        self.assertEqual(3, self.adjust(0.01)[0])

    def test_pitch_dark_idle_room_uses_lowest_foreground(self):
        self.assertEqual((1, 0), self.adjust(0.0))

    def test_not_gloomy_enforces_minimum_foreground_of_three(self):
        self.env.content.show_volume_meter = True

        self.assertEqual((3, 0), self.adjust(0.0))

    def test_visual_effect_overrides_colors_near_alarm(self):
        with frozen_now(self.now):
            self.env.content.update_next_alarm(
                next_alarm_info_at(
                    self.now + datetime.timedelta(minutes=1), with_visual_effect=True
                )
            )
            fg, bg = self.adjust(1.0)

        self.assertEqual(15, bg)
        self.assertEqual(3, fg)
        self.assertTrue(self.formatter._visual_effect_active)

    def test_visual_effect_flag_resets_once_effect_ends(self):
        with frozen_now(self.now):
            self.env.content.update_next_alarm(
                next_alarm_info_at(
                    self.now + datetime.timedelta(minutes=1), with_visual_effect=True
                )
            )
            self.formatter.adjust_display()
            self.assertTrue(self.formatter._visual_effect_active)

            self.env.content.update_next_alarm(
                next_alarm_info_at(
                    self.now + datetime.timedelta(hours=5), with_visual_effect=True
                )
            )
            self.formatter.adjust_display()

        self.assertFalse(self.formatter._visual_effect_active)
        self.assertEqual(0, self.formatter.background_color(ColorType.IN16))

    def test_alarm_without_visual_effect_does_not_change_colors(self):
        with frozen_now(self.now):
            self.env.content.update_next_alarm(
                next_alarm_info_at(self.now + datetime.timedelta(minutes=1))
            )
            self.assertEqual((15, 0), self.adjust(1.0))

    def test_adjust_by_alarm_visual_effect_accepts_none(self):
        self.formatter._visual_effect_active = True

        self.formatter.adjust_display_by_alarm_visual_effect(None)

        self.assertFalse(self.formatter._visual_effect_active)

    def test_update_formatter_adjusts_without_alarm(self):
        self.env.content.room_brightness = RoomBrightness(1.0)

        self.formatter.update_formatter()

        self.assertEqual(15, self.formatter.foreground_color(color_type=ColorType.IN16))


class ClockStringFormattingTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment()
        self.formatter = self.env.formatter
        self.clock = datetime.datetime(2026, 3, 1, 7, 5)

    def test_clock_string_contains_blink_segment(self):
        self.assertEqual("7:05", self.formatter.format_clock_string(self.clock))

    def test_clock_string_replaces_blink_segment_with_space_when_hidden(self):
        self.assertEqual(
            "7 05", self.formatter.format_clock_string(self.clock, False)
        )

    def test_clock_string_honours_configured_format_and_segment(self):
        self.env.config.clock_format_string = "%H<blinkSegment>%M"
        self.env.config.blink_segment = "."

        self.assertEqual("07.05", self.formatter.format_clock_string(self.clock))

    def test_dseg7_clock_string_is_left_padded(self):
        self.assertEqual(
            "!`:05", self.formatter.format_dseg7_clock_string(self.clock)
        )

    def test_dseg7_clock_string_with_two_digit_hour_has_no_padding(self):
        clock = datetime.datetime(2026, 3, 1, 23, 45)

        self.assertEqual("23:45", self.formatter.format_dseg7_clock_string(clock))

    def test_dseg7_clock_string_blink_off(self):
        clock = datetime.datetime(2026, 3, 1, 23, 45)

        self.assertEqual(
            "23 45", self.formatter.format_dseg7_clock_string(clock, False)
        )

    def test_dseg7_string_substitutes_unsupported_glyphs(self):
        self.assertEqual("`51", self.formatter.format_dseg7_string("7SI"))

    def test_dseg7_string_lowercases_input(self):
        self.assertEqual("abc", self.formatter.format_dseg7_string("ABC"))

    def test_dseg7_string_pads_to_desired_length(self):
        self.assertEqual("!!!12", self.formatter.format_dseg7_string("12", 5))

    def test_dseg7_string_never_truncates(self):
        self.assertEqual("12345", self.formatter.format_dseg7_string("12345", 3))

    def test_dseg7_string_defaults_to_no_padding(self):
        self.assertEqual("1:2", self.formatter.format_dseg7_string("1:2"))

    def test_dseg7_string_empty(self):
        self.assertEqual("", self.formatter.format_dseg7_string(""))
        self.assertEqual("!!", self.formatter.format_dseg7_string("", 2))


class PostprocessImageTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment(brightness=1.0)
        self.formatter = self.env.formatter

    def test_image_unchanged_when_not_gloomy(self):
        image = Image.new("RGB", (9, 5), (200, 200, 200))

        self.assertIs(image, self.formatter.postprocess_image(image))

    def test_gloomy_image_keeps_size_and_rgb_mode(self):
        self.env.content.room_brightness = RoomBrightness(0.0)
        self.formatter.update_formatter()
        image = Image.new("RGB", (9, 6), (255, 255, 255))

        result = self.formatter.postprocess_image(image)

        self.assertEqual((9, 6), result.size)
        self.assertEqual("RGB", result.mode)

    def test_gloomy_image_is_dimmed_and_dithered_to_every_fourth_pixel(self):
        self.env.content.room_brightness = RoomBrightness(0.0)
        self.formatter.update_formatter()
        image = Image.new("RGB", (6, 4), (255, 255, 255))

        result = self.formatter.postprocess_image(image)

        lit = {
            (x, y) for x in range(6) for y in range(4) if result.getpixel((x, y)) != (0, 0, 0)
        }
        self.assertEqual({(x, y) for x in (0, 2, 4) for y in (0, 2)}, lit)
        self.assertEqual((16, 16, 16), result.getpixel((0, 0)))

    def test_gloomy_image_handles_odd_width(self):
        self.env.content.room_brightness = RoomBrightness(0.0)
        self.formatter.update_formatter()
        image = Image.new("RGB", (5, 3), (255, 255, 255))

        result = self.formatter.postprocess_image(image)

        self.assertEqual((16, 16, 16), result.getpixel((4, 2)))
        self.assertEqual((0, 0, 0), result.getpixel((3, 0)))

    def test_gloomy_background_pixels_stay_black(self):
        self.env.content.room_brightness = RoomBrightness(0.0)
        self.formatter.update_formatter()
        image = Image.new("RGB", (4, 4), (0, 0, 0))

        result = self.formatter.postprocess_image(image)

        self.assertIsNone(result.getbbox())


if __name__ == "__main__":
    unittest.main()
