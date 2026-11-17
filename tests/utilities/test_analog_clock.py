import datetime
import unittest

from PIL import Image, ImageDraw

from utils.analog_clock import AnalogClockGenerator

CLEAR = (0, 0, 0, 0)
RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
WHITE = (255, 255, 255, 255)

NO_HANDS = dict(hour_hand_width=0, minute_hand_width=0, second_hand_width=0)
NO_MARKINGS = dict(hour_markings_length=-1)


class ClockImageTest(unittest.TestCase):
    def test_image_is_square_rgba_sized_by_radius(self):
        image = AnalogClockGenerator().get_clock(10, 10, 10, clock_radius=20)

        self.assertEqual((41, 41), image.size)
        self.assertEqual("RGBA", image.mode)

    def test_default_radius(self):
        image = AnalogClockGenerator().get_clock(0, 0, 0)

        self.assertEqual((63, 63), image.size)

    def test_background_is_transparent_by_default(self):
        image = AnalogClockGenerator().get_clock(0, 0, 0)

        self.assertEqual(CLEAR, image.getpixel((0, 0)))

    def test_custom_background_color(self):
        image = AnalogClockGenerator(background_color=BLUE).get_clock(0, 0, 0)

        self.assertEqual(BLUE, image.getpixel((0, 0)))

    def test_something_is_drawn(self):
        image = AnalogClockGenerator().get_clock(3, 15, 30)

        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_origin_is_drawn_in_center(self):
        generator = AnalogClockGenerator(
            origin_color=GREEN, **NO_HANDS, **NO_MARKINGS
        )

        image = generator.get_clock(0, 0, 0, clock_radius=28)

        self.assertEqual(GREEN, image.getpixel((28, 28)))
        self.assertEqual(GREEN, image.getpixel((28 + 3, 28)))
        self.assertEqual(CLEAR, image.getpixel((28 + 6, 28)))

    def test_with_everything_disabled_only_background_remains(self):
        generator = AnalogClockGenerator(origin_color=CLEAR, **NO_HANDS, **NO_MARKINGS)

        self.assertIsNone(generator.get_clock(5, 5, 5).getchannel("A").getbbox())


class HandOrientationTest(unittest.TestCase):
    def second_hand_pixel(self, second, dx, dy, radius=30):
        generator = AnalogClockGenerator(
            second_hand_color=RED,
            origin_color=CLEAR,
            hour_hand_width=0,
            minute_hand_width=0,
            second_hand_width=1,
            **NO_MARKINGS,
        )
        image = generator.get_clock(0, 0, second, clock_radius=radius)
        return image.getpixel((radius + dx, radius + dy))

    def test_second_hand_points_up_at_zero(self):
        self.assertEqual(RED, self.second_hand_pixel(0, 0, -15))
        self.assertEqual(CLEAR, self.second_hand_pixel(0, 0, 15))

    def test_second_hand_points_right_at_fifteen(self):
        self.assertEqual(RED, self.second_hand_pixel(15, 10, 0))
        self.assertEqual(CLEAR, self.second_hand_pixel(15, -10, 0))

    def test_second_hand_points_down_at_thirty(self):
        self.assertEqual(RED, self.second_hand_pixel(30, 0, 15))
        self.assertEqual(CLEAR, self.second_hand_pixel(30, 0, -15))

    def test_second_hand_points_left_at_forty_five(self):
        self.assertEqual(RED, self.second_hand_pixel(45, -10, 0))
        self.assertEqual(CLEAR, self.second_hand_pixel(45, 10, 0))

    def test_hour_hand_points_right_at_three(self):
        generator = AnalogClockGenerator(
            hour_hand_color=BLUE,
            origin_color=CLEAR,
            minute_hand_width=0,
            second_hand_width=0,
            hour_hand_width=1,
            **NO_MARKINGS,
        )

        image = generator.get_clock(3, 0, 0, clock_radius=35)

        self.assertEqual(BLUE, image.getpixel((35 + 10, 35)))
        self.assertEqual(CLEAR, image.getpixel((35, 35 - 10)))

    def test_hour_hand_uses_twelve_hour_dial(self):
        generator = AnalogClockGenerator(
            hour_hand_color=BLUE,
            origin_color=CLEAR,
            minute_hand_width=0,
            second_hand_width=0,
            hour_hand_width=3,
            **NO_MARKINGS,
        )

        image = generator.get_clock(15, 0, 0, clock_radius=35)

        self.assertEqual(BLUE, image.getpixel((35 + 10, 35)))
        self.assertEqual(CLEAR, image.getpixel((35 - 10, 35)))

    def test_minute_hand_points_down_at_thirty_minutes(self):
        generator = AnalogClockGenerator(
            minute_hand_color=GREEN,
            origin_color=CLEAR,
            hour_hand_width=0,
            second_hand_width=0,
            minute_hand_width=1,
            **NO_MARKINGS,
        )

        image = generator.get_clock(0, 30, 0, clock_radius=30)

        self.assertEqual(GREEN, image.getpixel((30, 30 + 20)))
        self.assertEqual(CLEAR, image.getpixel((30, 30 - 20)))

    def test_minute_hand_is_shorter_than_second_hand(self):
        generator = AnalogClockGenerator(
            minute_hand_color=GREEN,
            origin_color=CLEAR,
            hour_hand_width=0,
            second_hand_width=0,
            minute_hand_width=1,
            **NO_MARKINGS,
        )

        image = generator.get_clock(0, 0, 0, clock_radius=40)

        self.assertEqual(GREEN, image.getpixel((40, 40 - 35)))
        self.assertEqual(CLEAR, image.getpixel((40, 40 - 39)))

    def test_hands_have_independent_colors(self):
        generator = AnalogClockGenerator(
            hour_hand_color=RED,
            minute_hand_color=GREEN,
            second_hand_color=BLUE,
            origin_color=CLEAR,
            hour_hand_width=3,
            minute_hand_width=3,
            second_hand_width=3,
            **NO_MARKINGS,
        )

        image = generator.get_clock(3, 0, 30, clock_radius=40)

        self.assertEqual(RED, image.getpixel((40 + 15, 40)))
        self.assertEqual(GREEN, image.getpixel((40, 40 - 30)))
        self.assertEqual(BLUE, image.getpixel((40, 40 + 30)))

    def test_hands_move_with_time(self):
        generator = AnalogClockGenerator()

        a = generator.get_clock(1, 0, 0)
        b = generator.get_clock(1, 0, 30)

        self.assertNotEqual(a.tobytes(), b.tobytes())


class CurrentClockTest(unittest.TestCase):
    def test_get_current_clock_uses_given_time(self):
        generator = AnalogClockGenerator()
        moment = datetime.datetime(2026, 3, 1, 4, 20, 35)

        self.assertEqual(
            generator.get_clock(4, 20, 35, 31).tobytes(),
            generator.get_current_clock(moment).tobytes(),
        )

    def test_get_current_clock_honours_radius(self):
        image = AnalogClockGenerator().get_current_clock(
            datetime.datetime(2026, 3, 1, 4, 20, 35), clock_radius=10
        )

        self.assertEqual((21, 21), image.size)


class HourMarkingsTest(unittest.TestCase):
    def setUp(self):
        self.generator = AnalogClockGenerator()
        self.image = Image.new("RGBA", (61, 61), CLEAR)
        self.draw = ImageDraw.Draw(self.image)

    def test_markings_are_drawn_on_the_ring(self):
        self.generator.draw_hour_markings(
            self.draw, 30, start_distance=20, length=8, color=RED, width=3
        )

        for point in ((30, 30 + 24), (30, 30 - 24), (30 + 24, 30), (30 - 24, 30)):
            self.assertEqual(RED, self.image.getpixel(point))
        self.assertEqual(CLEAR, self.image.getpixel((30, 30)))
        self.assertEqual(CLEAR, self.image.getpixel((30, 30 + 12)))

    def test_generated_clock_has_markings_in_outer_ring_only(self):
        generator = AnalogClockGenerator(
            origin_color=CLEAR,
            hour_markings_length=10,
            hour_markings_width=1,
            **NO_HANDS,
        )

        image = generator.get_clock(0, 0, 0, clock_radius=30)

        self.assertEqual(WHITE, image.getpixel((30, 30 - 25)))
        self.assertEqual(CLEAR, image.getpixel((30, 30 - 10)))

    def test_negative_length_draws_nothing(self):
        self.generator.draw_hour_markings(self.draw, 30, length=-1)

        self.assertIsNone(self.image.getbbox())

    def test_negative_width_draws_nothing(self):
        self.generator.draw_hour_markings(self.draw, 30, 20, 5, width=-1)

        self.assertIsNone(self.image.getbbox())

    def test_zero_length_marking_is_accepted(self):
        self.generator.draw_hour_markings(self.draw, 30, 20, 0, width=1)


class DrawHandTest(unittest.TestCase):
    def setUp(self):
        self.generator = AnalogClockGenerator()
        self.image = Image.new("RGBA", (41, 41), CLEAR)
        self.draw = ImageDraw.Draw(self.image)

    def test_zero_width_hand_is_skipped(self):
        self.generator.draw_hand(self.draw, 20, 90, 15, RED, width=0)

        self.assertIsNone(self.image.getbbox())

    def test_negative_width_hand_is_skipped(self):
        self.generator.draw_hand(self.draw, 20, 90, 15, RED, width=-3)

        self.assertIsNone(self.image.getbbox())

    def test_hand_extends_in_angle_direction(self):
        self.generator.draw_hand(self.draw, 20, 90, 15, RED, width=1)

        self.assertEqual(RED, self.image.getpixel((35, 20)))
        self.assertEqual(CLEAR, self.image.getpixel((5, 20)))


class ConfigurationTest(unittest.TestCase):
    def test_constructor_stores_dimensions(self):
        generator = AnalogClockGenerator(
            hour_markings_width=2,
            hour_markings_length=3,
            hour_hand_width=4,
            minute_hand_width=5,
            second_hand_width=6,
        )

        self.assertEqual(
            (2, 3, 4, 5, 6),
            (
                generator.hour_markings_width,
                generator.hour_markings_length,
                generator.hour_hand_width,
                generator.minute_hand_width,
                generator.second_hand_width,
            ),
        )

    def test_defaults_are_white_hands_on_transparent_background(self):
        generator = AnalogClockGenerator()

        self.assertEqual(WHITE, generator.hour_hand_color)
        self.assertEqual(WHITE, generator.second_hand_color)
        self.assertEqual(CLEAR, generator.background_color)


if __name__ == "__main__":
    unittest.main()
