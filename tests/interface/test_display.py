import datetime
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from luma.core.device import dummy as luma_dummy
from PIL import Image
from PyQt5 import QtCore, QtGui

from tests.interface.display_helpers import (  # sets QT_QPA_PLATFORM first
    DisplayEnvironment,
    make_coordinator,
    make_device,
    next_alarm_info_at,
)
from core.domain.alarm_definition_editor import (
    AlarmEditingService,
    AlarmProperty,
    DayPickerSession,
    EditorAction,
)
from core.domain.events import (
    ForcedDisplayUpdateEvent,
    StartupFinishedEvent,
    TerminateAppRequest,
)
from core.domain.mode_coordinator import ModeName
from core.domain.model import Mode, RoomBrightness
from core.interface.display import display as display_module
from core.interface.display.display import Display, qt_message_handler
from core.interface.display.format import ColorType
from tests.support import frozen_now, local_datetime, make_alarm, make_stream
from utils.geolocation import Weather

_ORIGINAL_INITIALIZE_QT_APP = Display.initialize_qt_app
_QT_APP = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])

BELL = "\uf49a"
WIFI_OFF = "\U000f05aa"


class RecordingPainter:
    """Delegates to a real QPainter and records every drawn text."""

    def __init__(self, painter):
        self._painter = painter
        self.texts = []

    def drawText(self, *args):
        self.texts.append(args[-1])
        return self._painter.drawText(*args)

    def __getattr__(self, name):
        return getattr(self._painter, name)


def non_black_pixels(image: Image.Image, box=None) -> int:
    region = image.crop(box) if box else image
    return sum(1 for pixel in region.getdata() if pixel != (0, 0, 0))


class DisplayTestCase(unittest.TestCase):
    brightness = 1.0

    def setUp(self):
        self.env = DisplayEnvironment(brightness=self.brightness)
        self.device = make_device()
        patcher = mock.patch.object(
            Display, "initialize_qt_app", lambda s: setattr(s, "app", _QT_APP)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.display = self.make_display(self.device)
        self.now = local_datetime(2026, 3, 15, 7, 30, 12)
        frozen = frozen_now(self.now)
        frozen.__enter__()
        self.addCleanup(frozen.__exit__, None, None, None)

    def make_display(self, device) -> Display:
        return Display(
            device,
            self.env.content,
            self.env.playback,
            self.env.formatter,
            self.env.context,
            self.env.bus,
        )

    def set_mode(self, mode_name, editing_service=None):
        self.env.context.mode_coordinator = make_coordinator(
            mode_name, editing_service
        )

    def set_next_alarm(self, delta: datetime.timedelta, **kwargs):
        self.env.content.update_next_alarm(
            next_alarm_info_at(self.now + delta, **kwargs)
        )

    def new_painter(self):
        image = QtGui.QImage(256, 64, QtGui.QImage.Format.Format_RGB888)
        image.fill(QtGui.QColor("black"))
        painter = QtGui.QPainter(image)
        recorder = RecordingPainter(painter)
        # the cleanup keeps recorder and image alive until painting has ended
        self.addCleanup(lambda: (painter.end(), recorder, image))
        return recorder

    def paint_texts(self):
        self.env.formatter.update_formatter()
        painter = self.new_painter()
        self.display.paint(painter)
        return painter.texts

    def render(self) -> Image.Image:
        self.display.refresh()
        return self.display.current_display_image


class QtMessageHandlerTest(unittest.TestCase):
    def check(self, mode, level):
        with mock.patch.object(display_module, "logger") as logger:
            qt_message_handler(mode, None, "hello")
        getattr(logger, level).assert_called_once()
        self.assertIn("hello", getattr(logger, level).call_args[0][0])

    def test_info_message_is_logged_as_info(self):
        self.check(QtCore.QtInfoMsg, "info")

    def test_warning_message_is_logged_as_warning(self):
        self.check(QtCore.QtWarningMsg, "warning")

    def test_critical_message_is_logged_as_error(self):
        self.check(QtCore.QtCriticalMsg, "error")

    def test_fatal_message_is_logged_as_critical(self):
        self.check(QtCore.QtFatalMsg, "critical")

    def test_debug_message_is_logged_as_debug(self):
        self.check(QtCore.QtDebugMsg, "debug")


class DisplayConstructionTest(DisplayTestCase):
    def test_buffer_matches_device_size(self):
        self.assertEqual(256, self.display.buffer_image.width())
        self.assertEqual(64, self.display.buffer_image.height())

    def test_buffer_size_follows_device(self):
        display = self.make_display(make_device(128, 32))

        self.assertEqual(
            (128, 32),
            (display.buffer_image.width(), display.buffer_image.height()),
        )

    def test_terminate_request_hides_device(self):
        self.env.bus.emit(TerminateAppRequest())

        self.device.hide.assert_called_once_with()

    def test_forced_update_is_ignored_before_startup_finished(self):
        self.env.bus.emit(ForcedDisplayUpdateEvent())

        self.device.display.assert_not_called()

    def test_forced_update_refreshes_after_startup_finished(self):
        self.env.bus.emit(StartupFinishedEvent())

        self.env.bus.emit(ForcedDisplayUpdateEvent())

        self.device.display.assert_called_once()

    def test_initialize_qt_app_installs_handler_and_creates_application(self):
        with mock.patch.object(
            display_module.QtCore, "qInstallMessageHandler"
        ) as install, mock.patch.object(
            display_module.QtGui, "QGuiApplication"
        ) as application:
            _ORIGINAL_INITIALIZE_QT_APP(self.display)

        install.assert_called_once_with(qt_message_handler)
        application.assert_called_once_with([])
        self.assertIs(application.return_value, self.display.app)


class RefreshTest(DisplayTestCase):
    def test_refresh_sends_rgb_image_of_device_size_to_device(self):
        self.display.refresh()

        (image,), _ = self.device.display.call_args
        self.assertEqual("RGB", image.mode)
        self.assertEqual((256, 64), image.size)
        self.assertIs(image, self.display.current_display_image)

    def test_default_view_draws_something(self):
        self.assertGreater(non_black_pixels(self.render()), 100)

    def test_refresh_clears_scrolling_flag(self):
        self.env.content.is_scrolling = True

        self.display.refresh()

        self.assertFalse(self.env.content.is_scrolling)

    def test_refresh_updates_formatter_colors(self):
        self.display.refresh()

        self.assertEqual(
            15,
            self.env.formatter.foreground_color(color_type=ColorType.IN16),
        )

    def test_device_assertion_error_is_swallowed(self):
        self.device.display.side_effect = AssertionError("bad size")

        self.display.refresh()

        self.assertIsNotNone(self.display.current_display_image)

    def test_other_device_errors_propagate(self):
        self.device.display.side_effect = RuntimeError("spi")

        with self.assertRaises(RuntimeError):
            self.display.refresh()

    def test_dummy_device_screenshot_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            shot = os.path.join(directory, "shot.png")
            device = luma_dummy(width=256, height=64, mode="RGB")
            with mock.patch.object(display_module, "display_shot_file", shot):
                self.make_display(device).refresh()

            with Image.open(shot) as saved:
                self.assertEqual((256, 64), saved.size)
            self.assertEqual("RGB", device.image.mode)

    def test_hardware_like_device_does_not_save_screenshot(self):
        with mock.patch.object(Image.Image, "save") as save:
            self.display.refresh()

        save.assert_not_called()

    def test_grab_widget_image_converts_buffer_to_rgb(self):
        self.display.buffer_image.fill(QtGui.QColor("#ff0000"))

        image = self.display.grab_widget_image()

        self.assertEqual("RGB", image.mode)
        self.assertEqual((256, 64), image.size)
        self.assertEqual((255, 0, 0), image.getpixel((10, 10)))


class SafeRefreshTest(DisplayTestCase):
    def test_refresh_is_called_and_lock_released(self):
        with mock.patch.object(self.display, "refresh") as refresh:
            self.display.safe_refresh_display()
            self.display.safe_refresh_display(object())

        self.assertEqual(2, refresh.call_count)
        self.assertFalse(self.display._refresh_lock.locked())

    def test_concurrent_refresh_is_skipped(self):
        self.display._refresh_lock.acquire()
        self.addCleanup(self.display._refresh_lock.release)
        with mock.patch.object(self.display, "refresh") as refresh:
            self.display.safe_refresh_display()

        refresh.assert_not_called()

    def test_exception_is_rendered_on_device_and_lock_released(self):
        with mock.patch.object(
            self.display, "refresh", side_effect=ValueError("boom")
        ), mock.patch.object(display_module, "canvas") as canvas, self.assertLogs(
            display_module.logger, "ERROR"
        ):
            self.display.safe_refresh_display()

        canvas.assert_called_once_with(self.device)
        draw = canvas.return_value.__enter__.return_value
        self.assertIn("boom", draw.text.call_args[0][1])
        self.assertFalse(self.display._refresh_lock.locked())

    def test_recovers_after_failed_refresh(self):
        with mock.patch.object(
            self.display, "refresh", side_effect=[ValueError("boom"), None]
        ) as refresh, mock.patch.object(display_module, "canvas"), self.assertLogs(
            display_module.logger, "ERROR"
        ):
            self.display.safe_refresh_display()
            self.display.safe_refresh_display()

        self.assertEqual(2, refresh.call_count)


class PaintDispatchTest(DisplayTestCase):
    PAINT_METHODS = [
        "_paint_default_dimmed",
        "_paint_default_normal",
        "_paint_alarm_view",
        "_paint_alarm_edit_view",
        "_paint_property_edit_view",
        "_paint_day_picker_view",
    ]

    def dispatched(self):
        with mock.patch.multiple(
            self.display, **{n: mock.DEFAULT for n in self.PAINT_METHODS}
        ) as mocks:
            self.display.paint(mock.MagicMock())
        return [n for n, m in mocks.items() if m.called]

    def test_default_mode_without_coordinator_paints_normal_view(self):
        self.assertEqual(["_paint_default_normal"], self.dispatched())

    def test_default_mode_in_dark_room_paints_dimmed_view(self):
        self.env.content.room_brightness = RoomBrightness(0.0)

        self.assertEqual(["_paint_default_dimmed"], self.dispatched())

    def test_each_menu_mode_paints_its_own_view(self):
        expected = {
            ModeName.ALARM_VIEW: "_paint_alarm_view",
            ModeName.ALARM_EDIT: "_paint_alarm_edit_view",
            ModeName.PROPERTY_EDIT: "_paint_property_edit_view",
            ModeName.DAY_PICKER: "_paint_day_picker_view",
        }
        for mode_name, method in expected.items():
            with self.subTest(mode=mode_name):
                self.set_mode(mode_name)
                self.assertEqual([method], self.dispatched())

    def test_menu_mode_in_dark_room_never_uses_dimmed_view(self):
        self.env.content.room_brightness = RoomBrightness(0.0)
        self.set_mode(ModeName.ALARM_VIEW)

        self.assertEqual(["_paint_alarm_view"], self.dispatched())


class DefaultNormalViewTest(DisplayTestCase):
    def test_clock_digits_and_separator_are_drawn(self):
        self.assertEqual(["7", ":", "3", "0"], self.paint_texts()[:4])

    def test_separator_is_not_drawn_when_blinking_off(self):
        self.env.content.show_blink_segment = False

        self.assertEqual(["7", "3", "0"], self.paint_texts()[:3])
        self.assertNotIn(":", self.paint_texts())

    def test_hidden_blink_segment_changes_image(self):
        shown = self.render().copy()
        self.env.content.show_blink_segment = False
        hidden = self.render()

        self.assertNotEqual(shown.tobytes(), hidden.tobytes())

    def test_clock_format_without_blink_marker_falls_back_to_hours_and_minutes(self):
        self.env.config.clock_format_string = "%H%M"

        self.assertEqual(["0", "7", ":", "3", "0"], self.paint_texts()[:5])

    def test_info_area_is_empty_without_weather_playback_or_alarm(self):
        texts = self.paint_texts()

        self.assertFalse(any("°C" in t or "Vol" in t for t in texts))
        self.assertEqual(0, non_black_pixels(self.render(), (170, 0, 256, 64)))

    def test_weather_temperature_is_shown(self):
        self.env.content.current_weather = Weather(0, 21.54)

        self.assertIn("21.5°C", self.paint_texts())

    def test_weather_without_temperature_is_omitted(self):
        self.env.content.current_weather = Weather(0, None)

        self.assertFalse(any("°C" in t for t in self.paint_texts()))

    def test_weather_symbol_is_drawn_when_code_is_known(self):
        self.env.content.current_weather = Weather(0, 10.0)
        symbol = self.env.content.current_weather.code.to_character()

        self.assertTrue(symbol)
        self.assertIn(symbol, self.paint_texts())

    def test_weather_symbol_is_skipped_for_unknown_code(self):
        self.env.content.current_weather = Weather(99999, 10.0)

        texts = self.paint_texts()

        self.assertEqual(["10.0°C"], texts[4:])

    def test_info_area_is_drawn_when_weather_present(self):
        self.env.content.current_weather = Weather(0, 21.5)

        self.assertGreater(non_black_pixels(self.render(), (170, 0, 256, 64)), 0)

    def test_playback_title_is_shown_while_playing(self):
        self.env.playback.playback_mode = Mode.Music
        self.env.playback.audio_stream = make_stream("Jazz FM")

        texts = self.paint_texts()

        self.assertIn("Jazz FM", texts)
        self.assertIn("\uf2eb", texts)

    def test_long_playback_title_scrolls(self):
        self.env.playback.playback_mode = Mode.Music
        self.env.playback.audio_stream = make_stream("A very long radio station name")

        self.paint_texts()

        self.assertTrue(self.env.content.is_scrolling)

    def test_short_playback_title_does_not_scroll(self):
        self.env.playback.playback_mode = Mode.Music
        self.env.playback.audio_stream = make_stream("FM")

        self.paint_texts()

        self.assertFalse(self.env.content.is_scrolling)

    def test_scroll_start_time_resets_only_when_title_changes(self):
        self.env.playback.playback_mode = Mode.Music
        self.env.playback.audio_stream = make_stream("One")
        with mock.patch.object(display_module.time, "time", return_value=100.0):
            self.paint_texts()
        self.assertEqual(100.0, self.display._playback_title_scroll_start_time)

        with mock.patch.object(display_module.time, "time", return_value=200.0):
            self.paint_texts()
            self.assertEqual(100.0, self.display._playback_title_scroll_start_time)
            self.env.playback.audio_stream = make_stream("Two")
            self.paint_texts()

        self.assertEqual(200.0, self.display._playback_title_scroll_start_time)
        self.assertEqual("Two", self.display._last_playback_title)

    def test_next_alarm_within_preview_is_shown(self):
        self.set_next_alarm(datetime.timedelta(hours=2))

        self.assertIn(f"{BELL} 09:30", self.paint_texts())

    def test_next_alarm_beyond_preview_is_hidden(self):
        self.set_next_alarm(datetime.timedelta(hours=13))

        self.assertFalse(any(BELL in t for t in self.paint_texts()))

    def test_volume_meter_shows_percentage(self):
        self.env.content.show_volume_meter = True
        self.env.playback.volume = 0.35

        self.assertIn("Vol: 35%", self.paint_texts())

    def test_at_most_three_info_items_are_shown_dropping_the_first(self):
        self.env.content.current_weather = Weather(99999, 10.0)
        self.env.playback.playback_mode = Mode.Music
        self.env.playback.audio_stream = make_stream("FM")
        self.set_next_alarm(datetime.timedelta(hours=1))
        self.env.content.show_volume_meter = True

        texts = self.paint_texts()

        self.assertNotIn("10.0°C", texts)
        self.assertIn("FM", texts)
        self.assertIn(f"{BELL} 08:30", texts)
        self.assertTrue(any(t.startswith("Vol:") for t in texts))

    def test_vertical_separator_line_is_drawn(self):
        self.assertGreater(non_black_pixels(self.render(), (160, 0, 161, 64)), 50)


class DefaultDimmedViewTest(DisplayTestCase):
    brightness = 0.0

    def test_clock_is_drawn_with_dseg7_padding(self):
        self.assertEqual("!`:30", self.paint_texts()[0])

    def test_clock_uses_blank_separator_when_blinking_off(self):
        self.env.content.show_blink_segment = False

        self.assertEqual("!` 30", self.paint_texts()[0])

    def test_rendering_is_dithered_and_dark(self):
        image = self.render()

        self.assertEqual("RGB", image.mode)
        self.assertGreater(non_black_pixels(image), 0)
        self.assertLessEqual(max(max(p) for p in image.getdata()), 16)

    def test_position_depends_on_day_to_avoid_burn_in(self):
        first = self.render().getbbox()
        with frozen_now(self.now + datetime.timedelta(days=1)):
            second = self.render().getbbox()

        self.assertNotEqual(first, second)

    def test_alarm_within_preview_shows_bell_and_time(self):
        self.set_next_alarm(datetime.timedelta(hours=1))

        texts = self.paint_texts()

        self.assertIn(BELL, texts)
        self.assertIn("08:30", texts)

    def test_alarm_label_replaces_bell(self):
        self.set_next_alarm(datetime.timedelta(hours=1), label="Wk")

        texts = self.paint_texts()

        self.assertIn("Wk", texts)
        self.assertNotIn(BELL, texts)

    def test_alarm_beyond_preview_is_hidden(self):
        self.set_next_alarm(datetime.timedelta(hours=20))

        self.assertNotIn(BELL, self.paint_texts())

    def test_offline_icon_is_shown_when_offline(self):
        self.env.context.environment.is_online = False

        self.assertIn(WIFI_OFF, self.paint_texts())

    def test_offline_icon_is_hidden_when_online(self):
        self.assertNotIn(WIFI_OFF, self.paint_texts())


class AlarmViewTest(DisplayTestCase):
    def make_service(self, alarm=None, index=0):
        return SimpleNamespace(
            current_alarm=alarm or make_alarm(recurring=["MONDAY", "FRIDAY"]),
            current_alarm_index=index,
            editing_session=None,
        )

    def test_nothing_is_drawn_without_editing_service(self):
        self.set_mode(ModeName.ALARM_VIEW, None)

        self.assertEqual([], self.paint_texts())

    def test_header_time_status_and_days_are_drawn(self):
        self.env.config.alarm_definitions.append(make_alarm())
        self.set_mode(ModeName.ALARM_VIEW, self.make_service())

        texts = self.paint_texts()

        self.assertEqual(["ALARM 1/2", "07:30", "\uf205", "Mo, Fr"], texts)

    def test_inactive_alarm_uses_off_icon(self):
        service = self.make_service(make_alarm(is_active=False, recurring=["MONDAY"]))
        self.set_mode(ModeName.ALARM_VIEW, service)

        self.assertEqual("\uf204", self.paint_texts()[2])

    def test_new_alarm_is_labelled_as_such(self):
        self.set_mode(ModeName.ALARM_VIEW, self.make_service(make_alarm(id=None)))

        self.assertEqual("New Alarm", self.paint_texts()[3])

    def test_long_day_list_is_abbreviated(self):
        alarm = make_alarm(recurring=["MONDAY"])
        alarm.to_day_string = lambda: "Mo, Tu, We, Th, Fr, Sa, Su"
        self.set_mode(ModeName.ALARM_VIEW, self.make_service(alarm))

        self.assertEqual("Mo, Tu, We, ...", self.paint_texts()[3])

    def test_alarm_without_recurrence_or_date_is_reported_invalid(self):
        alarm = make_alarm(recurring=None, onetime=None)
        self.set_mode(ModeName.ALARM_VIEW, self.make_service(alarm))

        self.assertEqual("Invalid", self.paint_texts()[3])

    def test_time_is_zero_padded(self):
        service = self.make_service(make_alarm(hour=6, minute=5, recurring=["MONDAY"]))
        self.set_mode(ModeName.ALARM_VIEW, service)

        self.assertEqual("06:05", self.paint_texts()[1])

    def test_rendering_contains_pixels(self):
        self.set_mode(ModeName.ALARM_VIEW, self.make_service())

        self.assertGreater(non_black_pixels(self.render()), 50)

    def test_works_with_real_editing_service_for_new_alarm_slot(self):
        self.env.config.alarm_definitions.append(make_alarm())
        service = AlarmEditingService(self.env.context)
        service._alarm_index = 1
        self.set_mode(ModeName.ALARM_VIEW, service)

        texts = self.paint_texts()

        self.assertEqual("ALARM 2/2", texts[0])
        self.assertEqual("New Alarm", texts[3])


class EditViewTestCase(DisplayTestCase):
    mode_name = None

    def edit_service(self, prop, value=None, session=True):
        editing_session = (
            SimpleNamespace(get_current_value=lambda: value, day_picker_session=None)
            if session
            else None
        )
        return SimpleNamespace(property_to_edit=prop, editing_session=editing_session)

    def paint_for(self, prop, value=None):
        self.set_mode(self.mode_name, self.edit_service(prop, value))
        return self.paint_texts()

    def render_for(self, prop, value=None):
        self.set_mode(self.mode_name, self.edit_service(prop, value))
        return self.render()


class AlarmEditViewTest(EditViewTestCase):
    mode_name = ModeName.ALARM_EDIT

    def test_nothing_drawn_without_service_or_session(self):
        self.set_mode(self.mode_name, None)
        self.assertEqual([], self.paint_texts())
        self.set_mode(
            self.mode_name, self.edit_service(AlarmProperty.HOUR, session=False)
        )
        self.assertEqual([], self.paint_texts())

    def test_property_name_replaces_underscores(self):
        self.assertEqual("IS ACTIVE", self.paint_for(AlarmProperty.IS_ACTIVE, True)[0])

    def test_fade_in_and_volume_have_friendly_names(self):
        self.assertEqual("FADE IN", self.paint_for(AlarmProperty.FADE_IN, 30)[0])
        self.assertEqual(
            "VOLUME", self.paint_for(AlarmProperty.AUDIO_EFFECT_VOLUME, 0.5)[0]
        )

    def test_editor_actions_are_shown_without_value(self):
        for action in EditorAction:
            with self.subTest(action=action):
                self.assertEqual([action.value.upper()], self.paint_for(action))

    def test_plain_value_is_stringified(self):
        self.assertEqual("7", self.paint_for(AlarmProperty.HOUR, 7)[1])

    def test_recurring_value_shows_day_count(self):
        self.assertEqual(
            "2 days", self.paint_for(AlarmProperty.RECURRING, ["MONDAY", "FRIDAY"])[1]
        )

    def test_onetime_value_is_formatted_as_relative_date(self):
        self.assertEqual(
            "today", self.paint_for(AlarmProperty.ONETIME, self.now.date())[1]
        )

    def test_audio_effect_is_title_cased_or_none(self):
        self.assertEqual("None", self.paint_for(AlarmProperty.AUDIO_EFFECT, None)[1])
        self.assertEqual("Radio", self.paint_for(AlarmProperty.AUDIO_EFFECT, "radio")[1])

    def test_volume_is_shown_as_percentage(self):
        self.assertEqual(
            "35%", self.paint_for(AlarmProperty.AUDIO_EFFECT_VOLUME, 0.35)[1]
        )

    def test_visual_effect_is_yes_or_no(self):
        self.assertEqual("yes", self.paint_for(AlarmProperty.VISUAL_EFFECT, True)[1])
        self.assertEqual("no", self.paint_for(AlarmProperty.VISUAL_EFFECT, False)[1])

    def test_rendering_contains_pixels(self):
        self.assertGreater(
            non_black_pixels(self.render_for(AlarmProperty.HOUR, 7)), 50
        )


class PropertyEditViewTest(EditViewTestCase):
    mode_name = ModeName.PROPERTY_EDIT

    def test_nothing_drawn_without_service_or_session(self):
        self.set_mode(self.mode_name, None)
        self.assertEqual([], self.paint_texts())
        self.set_mode(
            self.mode_name, self.edit_service(AlarmProperty.HOUR, session=False)
        )
        self.assertEqual([], self.paint_texts())

    def test_hour_is_zero_padded_between_arrows(self):
        self.assertEqual(
            ["SET HOUR", "\uf053", "\uf054", "07"],
            self.paint_for(AlarmProperty.HOUR, 7),
        )

    def test_minute_is_zero_padded(self):
        self.assertEqual("05", self.paint_for(AlarmProperty.MIN, 5)[-1])

    def test_recurring_days_are_abbreviated(self):
        self.assertEqual(
            "MO,FR", self.paint_for(AlarmProperty.RECURRING, ["MONDAY", "FRIDAY"])[-1]
        )

    def test_recurring_with_many_days_still_renders(self):
        days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]

        self.assertEqual("MO,TU,WE,TH,FR", self.paint_for(AlarmProperty.RECURRING, days)[-1])

    def test_onetime_uses_relative_date(self):
        tomorrow = self.now.date() + datetime.timedelta(days=1)

        self.assertEqual(
            "tomorrow", self.paint_for(AlarmProperty.ONETIME, tomorrow)[-1]
        )

    def test_audio_effect_is_title_cased(self):
        self.assertEqual("Radio", self.paint_for(AlarmProperty.AUDIO_EFFECT, "radio")[-1])
        self.assertEqual("None", self.paint_for(AlarmProperty.AUDIO_EFFECT, "")[-1])

    def test_visual_effect_is_yes_or_no(self):
        self.assertEqual("yes", self.paint_for(AlarmProperty.VISUAL_EFFECT, True)[-1])
        self.assertEqual("no", self.paint_for(AlarmProperty.VISUAL_EFFECT, False)[-1])

    def test_alarm_label_shows_dash_when_empty(self):
        self.assertEqual("\u2014", self.paint_for(AlarmProperty.ALARM_LABEL, "")[-1])
        self.assertEqual("Work", self.paint_for(AlarmProperty.ALARM_LABEL, "Work")[-1])

    def test_fade_in_shows_progress_bar_with_seconds(self):
        self.assertEqual(
            ["SET FADE IN", "60s"], self.paint_for(AlarmProperty.FADE_IN, 60)
        )

    def test_fade_in_zero_is_off(self):
        self.assertEqual("off", self.paint_for(AlarmProperty.FADE_IN, 0)[-1])

    def test_volume_shows_progress_bar_with_percentage(self):
        self.assertEqual(
            ["SET VOLUME", "45%"],
            self.paint_for(AlarmProperty.AUDIO_EFFECT_VOLUME, 0.45),
        )

    def test_progress_bar_fill_grows_with_value(self):
        bar = (10, 26, 246, 52)
        low = non_black_pixels(self.render_for(AlarmProperty.AUDIO_EFFECT_VOLUME, 0.1), bar)
        high = non_black_pixels(self.render_for(AlarmProperty.AUDIO_EFFECT_VOLUME, 0.9), bar)

        self.assertGreater(high, low)

    def test_empty_progress_bar_still_draws_outline(self):
        image = self.render_for(AlarmProperty.AUDIO_EFFECT_VOLUME, 0.0)

        self.assertGreater(non_black_pixels(image, (10, 26, 246, 52)), 0)

    def test_rendering_contains_pixels(self):
        self.assertGreater(
            non_black_pixels(self.render_for(AlarmProperty.HOUR, 7)), 50
        )


class DayPickerViewTest(EditViewTestCase):
    def day_picker_service(self, active=("MONDAY",), cursor=0):
        picker = DayPickerSession(list(active))
        picker.navigate(cursor)
        return SimpleNamespace(
            property_to_edit=AlarmProperty.RECURRING,
            editing_session=SimpleNamespace(day_picker_session=picker),
        )

    def test_nothing_drawn_without_service_session_or_picker(self):
        self.set_mode(ModeName.DAY_PICKER, None)
        self.assertEqual([], self.paint_texts())
        self.set_mode(
            ModeName.DAY_PICKER,
            self.edit_service(AlarmProperty.RECURRING, session=False),
        )
        self.assertEqual([], self.paint_texts())
        self.set_mode(ModeName.DAY_PICKER, self.edit_service(AlarmProperty.RECURRING))
        self.assertEqual([], self.paint_texts())

    def test_header_days_and_ok_cell_are_drawn(self):
        self.set_mode(ModeName.DAY_PICKER, self.day_picker_service())

        texts = self.paint_texts()

        self.assertEqual("SELECT DAYS", texts[0])
        labels = [t for t in texts if len(t) == 2]
        self.assertEqual(["MO", "TU", "WE", "TH", "FR", "SA", "SU", "OK"], labels)

    def test_toggle_icons_reflect_active_days(self):
        self.set_mode(
            ModeName.DAY_PICKER, self.day_picker_service(active=("MONDAY", "SUNDAY"))
        )

        icons = [t for t in self.paint_texts() if t in ("\uf204", "\uf205")]

        self.assertEqual(
            ["\uf204", "\uf205", "\uf205", "\uf205", "\uf205", "\uf205", "\uf204"],
            icons,
        )

    def test_cursor_cell_is_highlighted(self):
        cell = 256 // 8
        self.set_mode(ModeName.DAY_PICKER, self.day_picker_service(cursor=0))
        on_monday = self.render().copy()
        self.set_mode(ModeName.DAY_PICKER, self.day_picker_service(cursor=7))
        on_ok = self.render()

        first_cell = (0, 16, cell, 64)
        last_cell = (7 * cell, 16, 8 * cell, 64)
        self.assertGreater(non_black_pixels(on_monday, first_cell), cell * 40)
        self.assertLess(non_black_pixels(on_ok, first_cell), cell * 40)
        self.assertGreater(non_black_pixels(on_ok, last_cell), cell * 40)

    def test_rendering_is_rgb_and_device_sized(self):
        self.set_mode(ModeName.DAY_PICKER, self.day_picker_service())

        image = self.render()

        self.assertEqual(("RGB", (256, 64)), (image.mode, image.size))


class FormatDateTest(DisplayTestCase):
    def test_none(self):
        self.assertEqual("None", self.display._format_date(None))

    def test_today(self):
        self.assertEqual("today", self.display._format_date(self.now.date()))

    def test_tomorrow(self):
        tomorrow = self.now.date() + datetime.timedelta(days=1)

        self.assertEqual("tomorrow", self.display._format_date(tomorrow))

    def test_yesterday_is_absolute(self):
        yesterday = self.now.date() - datetime.timedelta(days=1)

        self.assertEqual("2026-03-14", self.display._format_date(yesterday))

    def test_later_date_is_iso_formatted(self):
        self.assertEqual(
            "2026-12-31", self.display._format_date(datetime.date(2026, 12, 31))
        )

    def test_month_boundary_tomorrow(self):
        with frozen_now(local_datetime(2026, 2, 28, 23, 0)):
            self.assertEqual(
                "tomorrow", self.display._format_date(datetime.date(2026, 3, 1))
            )


class DrawHelpersTest(DisplayTestCase):
    LONG_TEXT = "a very long text that does not fit into the rect"

    def font(self, size=12):
        return self.env.formatter.info_font(size=size)

    def draw_scrolling(self, painter, rect, text, start_time=0.0, now=1.0):
        with mock.patch.object(display_module.time, "time", return_value=now):
            self.display._draw_scrolling_text(
                painter, rect, text, self.font(), QtGui.QColor("white"), start_time
            )

    def test_short_text_is_drawn_once_without_scrolling(self):
        painter = self.new_painter()

        self.draw_scrolling(painter, QtCore.QRect(0, 0, 200, 20), "short")

        self.assertEqual(["short"], painter.texts)
        self.assertFalse(self.env.content.is_scrolling)

    def test_long_text_marks_display_as_scrolling(self):
        painter = self.new_painter()

        self.draw_scrolling(painter, QtCore.QRect(0, 0, 60, 20), self.LONG_TEXT)

        self.assertTrue(self.env.content.is_scrolling)
        self.assertEqual(self.LONG_TEXT, painter.texts[0])

    def test_long_text_waits_then_moves_left(self):
        positions = []

        class Spy(RecordingPainter):
            def drawText(self, *args):
                positions.append(args[0])
                return super().drawText(*args)

        for now in (1.0, 2.0, 5.0):
            image = QtGui.QImage(256, 64, QtGui.QImage.Format.Format_RGB888)
            painter = QtGui.QPainter(image)
            self.draw_scrolling(
                Spy(painter), QtCore.QRect(0, 0, 60, 20), self.LONG_TEXT, now=now
            )
            painter.end()

        first_x_per_call = positions[0], positions[1], positions[2]
        self.assertEqual(0, first_x_per_call[0])
        self.assertEqual(0, first_x_per_call[1])
        self.assertLess(first_x_per_call[2], 0)

    def test_draw_clock_draws_all_characters(self):
        painter = self.new_painter()

        self.display._draw_clock(
            painter,
            QtCore.QRect(0, 0, 155, 64),
            "12",
            "34",
            ":",
            True,
            QtGui.QColor("white"),
            self.env.formatter.clock_font(size=30),
        )

        self.assertEqual(["1", "2", ":", "3", "4"], painter.texts)

    def test_draw_clock_omits_separator_when_not_shown(self):
        painter = self.new_painter()

        self.display._draw_clock(
            painter,
            QtCore.QRect(0, 0, 155, 64),
            "12",
            "34",
            ":",
            False,
            QtGui.QColor("white"),
            self.env.formatter.clock_font(size=30),
        )

        self.assertEqual(["1", "2", "3", "4"], painter.texts)


if __name__ == "__main__":
    unittest.main()
