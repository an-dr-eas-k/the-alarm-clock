import io
import os
import unittest
from unittest import mock

from PIL import Image, ImageFont

from utils import drawing
from utils.drawing import (
    ComposableImage,
    ImageComposition,
    PresentationFont,
    PresentationFontSingleton,
    Scroller,
    Synchroniser,
    get_concat_h,
    get_concat_h_multi_blank,
    get_concat_v,
    grayscale_to_color,
    text_to_image,
)

RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)


def solid(width, height, color=RED):
    return Image.new("RGBA", (width, height), color)


class ConcatenationTest(unittest.TestCase):
    def test_horizontal_concat_adds_widths_and_uses_max_height(self):
        result = get_concat_h(solid(4, 2), solid(6, 8))

        self.assertEqual((10, 8), result.size)
        self.assertEqual("RGBA", result.mode)

    def test_horizontal_concat_vertically_centers_smaller_image(self):
        result = get_concat_h(solid(2, 2, RED), solid(2, 6, GREEN))

        self.assertEqual(RED, result.getpixel((0, 2)))
        self.assertEqual(RED, result.getpixel((1, 3)))
        self.assertEqual((0, 0, 0, 0), result.getpixel((0, 0)))
        self.assertEqual(GREEN, result.getpixel((2, 0)))

    def test_vertical_concat_adds_heights_and_uses_max_width(self):
        result = get_concat_v(solid(8, 3), solid(2, 5))

        self.assertEqual((8, 8), result.size)

    def test_vertical_concat_horizontally_centers_narrow_image(self):
        result = get_concat_v(solid(2, 2, RED), solid(6, 2, GREEN))

        self.assertEqual(RED, result.getpixel((2, 0)))
        self.assertEqual((0, 0, 0, 0), result.getpixel((0, 0)))
        self.assertEqual(GREEN, result.getpixel((0, 2)))

    def test_background_color_is_applied(self):
        result = get_concat_h(solid(1, 1), solid(1, 3), bg_color=BLUE)

        self.assertEqual(BLUE, result.getpixel((0, 0)))

    def test_multi_concat_joins_all_images_left_to_right(self):
        result = get_concat_h_multi_blank([solid(2, 2), solid(3, 4), solid(5, 3)])

        self.assertEqual((10, 4), result.size)

    def test_multi_concat_of_single_image_returns_it(self):
        image = solid(3, 3)

        self.assertIs(image, get_concat_h_multi_blank([image]))

    def test_multi_concat_of_empty_list_raises(self):
        with self.assertRaises(IndexError):
            get_concat_h_multi_blank([])

    def test_multi_concat_consumes_given_list(self):
        images = [solid(1, 1), solid(1, 1)]

        get_concat_h_multi_blank(images)

        self.assertEqual(1, len(images))


class GrayscaleToColorTest(unittest.TestCase):
    def test_black_and_white(self):
        self.assertEqual(0, grayscale_to_color(0))
        self.assertEqual(0xFFFFFF, grayscale_to_color(255))

    def test_value_is_replicated_in_all_channels(self):
        self.assertEqual(0x808080, grayscale_to_color(0x80))


class TextToImageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = PresentationFont.get_font(PresentationFont.roboto_font, 20)

    def test_height_equals_font_size_and_mode_defaults_to_rgb(self):
        image = text_to_image("12:34", self.font, "white")

        self.assertEqual(20, image.height)
        self.assertEqual("RGB", image.mode)

    def test_text_is_drawn_in_foreground_color_on_black(self):
        image = text_to_image("HELLO", self.font, (255, 255, 255))

        self.assertIsNotNone(image.getbbox())
        self.assertEqual((0, 0, 0), image.getpixel((0, 0)))

    def test_wider_text_gives_wider_image(self):
        short = text_to_image("1", self.font, "white")
        long = text_to_image("1111", self.font, "white")

        self.assertGreater(long.width, short.width)

    def test_custom_background_color(self):
        image = text_to_image(" ", self.font, "white", bg_color=(9, 9, 9))

        self.assertEqual((9, 9, 9), image.getpixel((0, 0)))

    def test_custom_mode(self):
        image = text_to_image("A", self.font, 255, bg_color=0, mode="L")

        self.assertEqual("L", image.mode)
        self.assertIsNotNone(image.getbbox())


class SolidComposable(ComposableImage):
    def __init__(self, image, position=None, present=True):
        super().__init__(position)
        self.image = image
        self.present = present

    def is_present(self):
        return self.present

    def draw(self):
        return self.image


class ComposableImageTest(unittest.TestCase):
    def test_default_position_is_origin(self):
        self.assertEqual((0, 0), ComposableImage().position(10, 10))

    def test_position_callback_receives_image_size(self):
        composable = ComposableImage(lambda w, h: (100 - w, 50 - h))

        self.assertEqual((90, 45), composable.position(10, 5))

    def test_base_class_is_not_present_and_cannot_draw(self):
        composable = ComposableImage()

        self.assertFalse(composable.is_present())
        with self.assertRaises(ValueError):
            composable.draw()

    def test_bounding_box_combines_position_and_dimensions(self):
        composable = ComposableImage(lambda w, h: (3, 4))
        composable.position(10, 5)
        composable.set_dimensions(10, 5)

        self.assertEqual((3, 4, 13, 9), composable.get_bounding_box())

    def test_bounding_box_before_layout_raises(self):
        with self.assertRaises(TypeError):
            ComposableImage().get_bounding_box()


class ImageCompositionTest(unittest.TestCase):
    def setUp(self):
        self.background = Image.new("RGB", (20, 10), (0, 0, 0))
        self.composition = ImageComposition(self.background)

    def test_call_returns_background_image(self):
        self.assertIs(self.background, self.composition())

    def test_refresh_pastes_present_images_at_their_position(self):
        self.composition.add_image(
            SolidComposable(solid(4, 3, RED), lambda w, h: (5, 2))
        )

        self.composition.refresh()

        self.assertEqual((255, 0, 0), self.background.getpixel((5, 2)))
        self.assertEqual((255, 0, 0), self.background.getpixel((8, 4)))
        self.assertEqual((0, 0, 0), self.background.getpixel((9, 4)))
        self.assertEqual((0, 0, 0), self.background.getpixel((4, 2)))

    def test_refresh_skips_images_that_are_not_present(self):
        self.composition.add_image(SolidComposable(solid(4, 3), present=False))

        self.composition.refresh()

        self.assertIsNone(self.background.getbbox())

    def test_refresh_clears_previous_content(self):
        self.background.paste((9, 9, 9), (0, 0, 20, 10))

        self.composition.refresh()

        self.assertIsNone(self.background.getbbox())

    def test_refresh_records_dimensions_on_composable(self):
        composable = SolidComposable(solid(4, 3), lambda w, h: (1, 1))
        self.composition.add_image(composable)

        self.composition.refresh()

        self.assertEqual((1, 1, 5, 4), composable.get_bounding_box())

    def test_later_images_are_drawn_over_earlier_ones(self):
        self.composition.add_image(SolidComposable(solid(4, 4, RED)))
        self.composition.add_image(SolidComposable(solid(2, 2, GREEN)))

        self.composition.refresh()

        self.assertEqual((0, 255, 0), self.background.getpixel((0, 0)))
        self.assertEqual((255, 0, 0), self.background.getpixel((3, 3)))

    def test_remove_image_stops_drawing_it(self):
        composable = SolidComposable(solid(4, 4))
        self.composition.add_image(composable)
        self.composition.remove_image(composable)

        self.composition.refresh()

        self.assertIsNone(self.background.getbbox())

    def test_remove_unknown_image_raises(self):
        with self.assertRaises(ValueError):
            self.composition.remove_image(SolidComposable(solid(1, 1)))

    def test_add_falsy_image_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.composition.add_image(None)

    def test_clear_removes_all_images(self):
        self.composition.add_image(SolidComposable(solid(4, 4)))
        self.composition.clear()

        self.composition.refresh()

        self.assertEqual([], self.composition.composed_images)
        self.assertIsNone(self.background.getbbox())

    def test_debug_mode_outlines_images(self):
        self.composition.debug = True
        self.addCleanup(setattr, self.composition, "debug", False)
        self.composition.add_image(SolidComposable(solid(6, 6, (0, 0, 0, 255))))

        self.composition.refresh()

        self.assertEqual((96, 96, 96), self.background.getpixel((0, 0)))
        self.assertEqual((0, 0, 0), self.background.getpixel((2, 2)))

    def test_empty_image_is_handled_in_debug_mode(self):
        self.composition.debug = True
        self.addCleanup(setattr, self.composition, "debug", False)
        self.composition.add_image(SolidComposable(Image.new("RGBA", (0, 0))))

        self.composition.refresh()


class SynchroniserTest(unittest.TestCase):
    def test_empty_synchroniser_is_synchronised(self):
        self.assertTrue(Synchroniser().is_synchronised())

    def test_busy_task_blocks_synchronisation_until_ready(self):
        synchroniser = Synchroniser()
        task = object()

        synchroniser.busy(task)
        self.assertFalse(synchroniser.is_synchronised())
        synchroniser.ready(task)
        self.assertTrue(synchroniser.is_synchronised())

    def test_one_busy_task_among_ready_ones_blocks(self):
        synchroniser = Synchroniser()
        a, b = object(), object()
        synchroniser.ready(a)
        synchroniser.busy(b)

        self.assertFalse(synchroniser.is_synchronised())


class ScrollerTest(unittest.TestCase):
    def run_ticks(self, scroller, image, count):
        positions = []
        for _ in range(count):
            scroller.tick(image)
            positions.append(scroller.image_x_pos)
        return positions

    def test_narrow_image_never_scrolls(self):
        scroller = Scroller(canvas_width=30, scroll_delay=1)
        image = Image.new("RGB", (20, 8))

        positions = self.run_ticks(scroller, image, 20)

        self.assertEqual({0}, set(positions))
        self.assertFalse(scroller.is_scrolling())

    def test_tick_returns_crop_of_canvas_width(self):
        scroller = Scroller(canvas_width=10, scroll_delay=1)

        result = scroller.tick(Image.new("RGB", (25, 8)))

        self.assertEqual((10, 8), result.size)
        self.assertTrue(scroller.is_scrolling())

    def test_waits_for_delay_before_scrolling(self):
        scroller = Scroller(canvas_width=10, scroll_delay=2, scroll_speed=3)
        image = Image.new("RGB", (30, 4))

        positions = self.run_ticks(scroller, image, 6)

        self.assertEqual([0, 0, 0, 3, 6, 9], positions)

    def test_scrolls_to_end_then_rewinds(self):
        scroller = Scroller(canvas_width=10, scroll_delay=1, scroll_speed=5)
        image = Image.new("RGB", (30, 4))

        positions = self.run_ticks(scroller, image, 30)

        self.assertEqual(20, max(positions))
        first_peak = positions.index(20)
        self.assertIn(0, positions[first_peak:])

    def test_scroller_restarts_after_rewind(self):
        scroller = Scroller(canvas_width=10, scroll_delay=1, scroll_speed=10)
        image = Image.new("RGB", (30, 4))

        positions = self.run_ticks(scroller, image, 40)

        rewind = positions.index(0, positions.index(20))
        self.assertIn(10, positions[rewind:])

    def test_rewind_resets_state_and_position(self):
        scroller = Scroller(canvas_width=10, scroll_delay=1)
        scroller.must_scroll = True
        scroller.image_x_pos = 7
        scroller.state = Scroller.WAIT_SYNC

        scroller.rewind()

        self.assertEqual(0, scroller.image_x_pos)
        self.assertEqual(Scroller.WAIT_SCROLL, scroller.state)

    def test_rewind_without_scrolling_keeps_position(self):
        scroller = Scroller(canvas_width=10, scroll_delay=1)
        scroller.must_scroll = False
        scroller.image_x_pos = 7

        scroller.rewind()

        self.assertEqual(7, scroller.image_x_pos)

    def test_is_waiting_counts_ticks_up_to_delay(self):
        scroller = Scroller(canvas_width=10, scroll_delay=2)

        self.assertEqual([True, True, False, True], [scroller.is_waiting() for _ in range(4)])

    def test_new_scroller_registers_itself_as_busy(self):
        synchroniser = Synchroniser()

        scroller = Scroller(10, 1, synchroniser=synchroniser)

        self.assertFalse(synchroniser.synchronised[id(scroller)])

    def test_scrollers_rewind_together(self):
        synchroniser = Synchroniser()
        fast = Scroller(10, 1, scroll_speed=10, synchroniser=synchroniser)
        slow = Scroller(10, 1, scroll_speed=1, synchroniser=synchroniser)
        image = Image.new("RGB", (20, 4))

        rewound_together = False
        fast_had_to_wait = False
        for _ in range(80):
            fast.tick(image)
            slow.tick(image)
            if fast.state == Scroller.WAIT_SYNC and slow.state == Scroller.SCROLLING:
                self.assertFalse(synchroniser.is_synchronised())
                self.assertGreater(slow.image_x_pos, 0)
                fast_had_to_wait = True
            if fast.image_x_pos == 0 and slow.image_x_pos == 0 and fast.ticks == 0:
                rewound_together = True
        self.assertTrue(fast_had_to_wait)
        self.assertTrue(rewound_together)

    def test_render_crops_at_current_offset(self):
        scroller = Scroller(canvas_width=4, scroll_delay=1)
        image = Image.new("RGB", (10, 2))
        image.paste((255, 0, 0), (6, 0, 10, 2))
        scroller.image_x_pos = 6

        result = scroller.render(image)

        self.assertEqual((255, 0, 0), result.getpixel((0, 0)))
        self.assertEqual((4, 2), result.size)


class PresentationFontTest(unittest.TestCase):
    def test_font_paths_point_to_existing_files(self):
        for path in (
            PresentationFont.bold_clock_font,
            PresentationFont.light_clock_font,
            PresentationFont.info_font,
            PresentationFont.roboto_font,
            PresentationFont.weather_font,
        ):
            self.assertTrue(os.path.isfile(path), path)

    def test_get_font_returns_truetype_font_of_requested_size(self):
        font = PresentationFont.get_font(PresentationFont.roboto_font, 24)

        self.assertIsInstance(font, ImageFont.FreeTypeFont)
        self.assertEqual(24, font.size)

    def test_get_font_default_size(self):
        self.assertEqual(
            50, PresentationFont.get_font(PresentationFont.roboto_font).size
        )

    def test_get_font_can_be_requested_repeatedly(self):
        first = PresentationFont.get_font(PresentationFont.light_clock_font, 10)
        second = PresentationFont.get_font(PresentationFont.light_clock_font, 12)

        self.assertEqual((10, 12), (first.size, second.size))

    def test_get_font_with_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            PresentationFont.get_font("/nonexistent/font.ttf")

    def test_get_font_with_invalid_font_data_raises(self):
        with tempfile_font(b"not a font") as path:
            with self.assertRaises(Exception):
                PresentationFont.get_font(path)

    def test_font_family_is_delegated_to_singleton(self):
        with mock.patch.object(
            type(PresentationFontSingleton()),
            "_get_cached_font_family",
            return_value="qfont",
        ) as getter:
            result = PresentationFont.get_font_family("x.ttf", 12, 50)

        self.assertEqual("qfont", result)
        getter.assert_called_once_with("x.ttf", 12, 50)


class tempfile_font:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        import tempfile

        self.dir = tempfile.TemporaryDirectory()
        path = os.path.join(self.dir.name, "broken.ttf")
        with open(path, "wb") as f:
            f.write(self.data)
        return path

    def __exit__(self, *exc):
        self.dir.cleanup()


class PresentationFontSingletonTest(unittest.TestCase):
    def setUp(self):
        self.singleton = PresentationFontSingleton()
        for cache in (
            type(PresentationFontSingleton())._font_cache,
            type(PresentationFontSingleton())._font_family_cache,
        ):
            snapshot = dict(cache)
            self.addCleanup(self._restore, cache, snapshot)

    @staticmethod
    def _restore(cache, snapshot):
        cache.clear()
        cache.update(snapshot)

    def test_is_a_singleton(self):
        self.assertIs(PresentationFontSingleton(), PresentationFontSingleton())

    def test_font_file_is_cached_and_rewound(self):
        path = PresentationFont.roboto_font
        type(self.singleton)._font_cache.pop(path, None)

        first = self.singleton._get_cached_font_file(path)
        first.read(10)
        second = self.singleton._get_cached_font_file(path)

        self.assertIs(first, second)
        self.assertEqual(0, second.tell())
        self.assertIsInstance(second, io.BytesIO)

    def test_missing_font_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.singleton._get_cached_font_file("/nonexistent/font.ttf")

    def test_font_family_is_created_once_per_key(self):
        qt_database = mock.MagicMock()
        qt_database.addApplicationFont.return_value = 3
        qt_database.applicationFontFamilies.return_value = ["Roboto Mono"]
        with mock.patch.object(drawing.QtGui, "QFontDatabase", qt_database), mock.patch.object(
            drawing.QtGui, "QFont", side_effect=lambda *a: a
        ) as qfont:
            first = self.singleton._get_cached_font_family("a.ttf", 14, 50)
            second = self.singleton._get_cached_font_family("a.ttf", 14, 50)

        self.assertEqual(("Roboto Mono", 14, 50), first)
        self.assertIs(first, second)
        qt_database.addApplicationFont.assert_called_once_with("a.ttf")
        qfont.assert_called_once_with("Roboto Mono", 14, 50)

    def test_font_family_unloadable_font_raises(self):
        qt_database = mock.MagicMock()
        qt_database.addApplicationFont.return_value = -1
        with mock.patch.object(drawing.QtGui, "QFontDatabase", qt_database):
            with self.assertRaises(ValueError):
                self.singleton._get_cached_font_family("broken.ttf", 14, 50)

    def test_font_family_without_families_raises(self):
        qt_database = mock.MagicMock()
        qt_database.addApplicationFont.return_value = 1
        qt_database.applicationFontFamilies.return_value = []
        with mock.patch.object(drawing.QtGui, "QFontDatabase", qt_database):
            with self.assertRaises(ValueError):
                self.singleton._get_cached_font_family("empty.ttf", 14, 50)


if __name__ == "__main__":
    unittest.main()
