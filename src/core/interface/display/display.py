import logging
import traceback
import time
import threading
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import Image

from PyQt5 import QtCore, QtGui

from core.domain.alarm_definition_editor import (
    AlarmProperty,
    DayPickerSession,
    EditorAction,
)
from core.domain.events import (
    AlarmStoppedEvent,
    ForcedDisplayUpdateEvent,
    StartupFinishedEvent,
    TerminateAppRequest,
)
from core.domain.model import (
    AlarmClockContext,
    Config,
    DisplayContentProvider,
    PlaybackContent,
    SpotifyStream,
)
from core.domain.mode_coordinator import ModeName
from core.interface.display.display_content import DisplayContent
from core.infrastructure.event_bus import EventBus
from core.interface.display.format import ColorType, DisplayFormatter

from utils.geolocation import GeoLocation

from resources.resources import display_shot_file

logger = logging.getLogger("tac.core.interface.display.display")


def qt_message_handler(mode, context, message: str):

    if mode == QtCore.QtInfoMsg:
        logger.info(f"Qt: {message}")
    elif mode == QtCore.QtWarningMsg:
        logger.warning(
            f"Qt: {message}\nStacktrace: {''.join(traceback.format_stack())}"
        )
    elif mode == QtCore.QtCriticalMsg:
        logger.error(f"Qt: {message}\nStacktrace: {''.join(traceback.format_stack())}")
    elif mode == QtCore.QtFatalMsg:
        logger.critical(
            f"Qt: {message}\nStacktrace: {''.join(traceback.format_stack())}"
        )
    else:
        logger.debug(f"Qt: {message}")


class Display(DisplayContentProvider):

    device: luma_device
    display_content: DisplayContent

    _last_playback_title: str = None
    _playback_title_scroll_start_time: float = 0

    def __init__(
        self,
        device: luma_device,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        display_formatter: DisplayFormatter,
        alarm_clock_context: AlarmClockContext,
        event_bus: EventBus = None,
    ) -> None:
        self.device = device
        logger.info("device mode: %s", self.device.mode)
        self.display_content = display_content
        self.playback_content = playback_content
        self.alarm_clock_context = alarm_clock_context
        self.event_bus = event_bus
        self.formatter = display_formatter
        self.initialize_qt_app()

        self.buffer_image = QtGui.QImage(
            self.device.width, self.device.height, QtGui.QImage.Format.Format_RGB888
        )

        self.current_layout_type = None
        self._refresh_lock = threading.Lock()

        self.event_bus.on(StartupFinishedEvent)(self.on_startup_finished)
        self.event_bus.on(TerminateAppRequest)(lambda _: self.device.hide())

    def on_startup_finished(self, _: StartupFinishedEvent):
        self.event_bus.on(ForcedDisplayUpdateEvent)(self.safe_refresh_display)

    def safe_refresh_display(self, _=None):
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self.refresh()
        except Exception as e:
            logger.error("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception!\n({e})", fill="white")
        finally:
            self._refresh_lock.release()

    def _draw_clock(
        self,
        painter,
        rect,
        hour_str,
        min_str,
        blink_char,
        show_blink,
        fg_color,
        font_obj,
    ):
        painter.save()
        painter.setFont(font_obj)
        fm = QtGui.QFontMetrics(font_obj)

        overlap = 12
        vertical_shift = 2

        # Calculate total width
        total_width = 0
        for i, char in enumerate(hour_str):
            total_width += fm.width(char) - (overlap if i < len(hour_str) - 1 else 0)
        total_width += -15 + fm.width(blink_char) - 10
        for i, char in enumerate(min_str):
            total_width += fm.width(char) - (overlap if i < len(min_str) - 1 else 0)

        # Center in rect
        x = rect.left() + (rect.width() - total_width) // 2
        base_y = rect.top() + (rect.height() + fm.ascent() - fm.descent()) // 2

        h, s, v, a = fg_color.getHsv()
        white_color = fg_color
        gray_color = QtGui.QColor.fromHsv(h, s, max(17, v - 18), a)

        # Draw Hours
        for i, char in enumerate(hour_str):
            painter.setPen(white_color if i == 0 else gray_color)
            y = base_y + (-vertical_shift if i == 0 else vertical_shift)
            painter.drawText(int(x), int(y), char)
            x += fm.width(char) - (overlap if i < len(hour_str) - 1 else 0)

        x += -15
        # Draw Separator
        if show_blink:
            painter.setPen(white_color)
            painter.drawText(int(x), int(base_y), blink_char)
        x += fm.width(blink_char) - 10

        # Draw Minutes
        for i, char in enumerate(min_str):
            painter.setPen(white_color if i == 0 else gray_color)
            y = base_y + (-vertical_shift if i == 0 else vertical_shift)
            painter.drawText(int(x), int(y), char)
            x += fm.width(char) - (overlap if i < len(min_str) - 1 else 0)

        painter.restore()

    def _draw_scrolling_text(
        self, painter, rect, text, font_obj, color, start_time, speed=30
    ):
        painter.save()
        painter.setFont(font_obj)
        painter.setPen(color)
        fm = QtGui.QFontMetrics(font_obj)
        text_width = fm.width(text)
        widget_width = rect.width()

        if text_width <= widget_width:
            painter.drawText(
                rect,
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                text,
            )
        else:
            self.display_content.is_scrolling = True
            elapsed = time.time() - start_time
            pause_duration = 2.0
            offset = (
                0 if elapsed < pause_duration else (elapsed - pause_duration) * speed
            )
            gap = 30
            total_cycle_width = text_width + gap
            current_offset = offset % total_cycle_width

            y = rect.top() + (rect.height() + fm.ascent() - fm.descent()) // 2

            painter.setClipRect(rect)

            x1 = rect.left() - current_offset
            if x1 + text_width > rect.left():
                painter.drawText(int(x1), int(y), text)

            x2 = x1 + total_cycle_width
            if x2 < rect.right():
                painter.drawText(int(x2), int(y), text)

        painter.restore()

    def paint(self, painter):
        mode = (
            self.alarm_clock_context.mode_coordinator.current_mode_name
            if self.alarm_clock_context.mode_coordinator
            else ModeName.DEFAULT
        )

        if mode == ModeName.DEFAULT:
            if self.formatter.be_gloomy():
                self._paint_default_dimmed(painter)
            else:
                self._paint_default_normal(painter)
        elif mode == ModeName.ALARM_VIEW:
            self._paint_alarm_view(painter)
        elif mode == ModeName.ALARM_EDIT:
            self._paint_alarm_edit_view(painter)
        elif mode == ModeName.PROPERTY_EDIT:
            self._paint_property_edit_view(painter)
        elif mode == ModeName.DAY_PICKER:
            self._paint_day_picker_view(painter)

    def _paint_default_dimmed(self, painter):
        now = GeoLocation().now()
        day = now.day
        # Screensaver-like movement to prevent burn-in
        x_offset = (day % 15) * 6 + 10
        y_offset = (day % 5) * 2 + 8  # Start at least 8px down to avoid clipping

        fg_color = QtGui.QColor(
            self.formatter.foreground_color(color_type=ColorType.INHEX)
        )
        painter.setPen(fg_color)

        # Clock
        clock_string = self.formatter.format_dseg7_clock_string(
            now, self.display_content.show_blink_segment
        )
        font = self.formatter.clock_font(size=18, weight=QtGui.QFont.Weight.Light)
        painter.setFont(font)
        painter.drawText(
            QtCore.QRect(x_offset, y_offset, 120, 25),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            clock_string,
        )

        # Next Alarm
        if (
            self.display_content.has_next_alarm()
            and self.display_content.next_alarm_info.minutes_until_alarm()
            <= self.display_content.alarm_clock_context.config.alarm_preview_hours * 60
        ):
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = self.formatter.format_clock_string(alarm_time)
            painter.setFont(self.formatter.info_font(size=12))
            painter.drawText(
                QtCore.QRect(x_offset + 95, y_offset, 100, 25),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                f"\uf49a {alarm_text}",
            )

        # WiFi
        if not self.display_content.get_is_online():
            painter.setFont(self.formatter.info_font(size=14))
            painter.drawText(
                QtCore.QRect(x_offset + 95, y_offset + 20, 50, 25),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                "\U000f05aa",
            )

    def _paint_default_normal(self, painter):
        fg_color = QtGui.QColor(
            self.formatter.foreground_color(color_type=ColorType.INHEX)
        )

        # Clock
        fmt = self.alarm_clock_context.config.clock_format_string
        parts = fmt.split("<blinkSegment>")
        hour_fmt, min_fmt = (parts[0], parts[1]) if len(parts) == 2 else ("%H", "%M")
        now = GeoLocation().now()

        self._draw_clock(
            painter,
            QtCore.QRect(0, 0, 155, self.device.height),
            now.strftime(hour_fmt),
            now.strftime(min_fmt),
            ":",
            self.display_content.show_blink_segment,
            fg_color,
            self.formatter.clock_font(size=42),
        )

        # Vertical Line
        painter.setPen(QtGui.QPen(fg_color, 1))
        painter.drawLine(160, 0, 160, self.device.height - 0)

        # Info Stack
        x_info = 170
        item_height = 22

        # Gather items to display
        items = []
        weather = self.display_content.current_weather
        if weather and weather.temperature is not None:
            items.append(("weather", weather))

        playback_title = self.display_content.current_playback_title()
        if playback_title:
            items.append(("playback", playback_title))

        if (
            self.display_content.has_next_alarm()
            and self.display_content.next_alarm_info.minutes_until_alarm()
            <= self.display_content.alarm_clock_context.config.alarm_preview_hours * 60
        ):
            items.append(("alarm", self.display_content.get_next_alarm()))

        if self.display_content.show_volume_meter:
            items.append(("volume", self.display_content.current_volume()))

        if len(items) > 3:
            items = items[1:]

        if items:
            total_stack_height = len(items) * item_height
            start_y = (self.device.height - total_stack_height) // 2

            for i, (item_type, data) in enumerate(items):
                rect = QtCore.QRect(
                    x_info,
                    start_y + i * item_height,
                    self.device.width - x_info,
                    item_height,
                )

                if item_type == "weather":
                    symbol = data.code.to_character() if data.code else None
                    if symbol:
                        painter.setFont(self.formatter.weather_font(size=13))
                        painter.drawText(
                            rect,
                            QtCore.Qt.AlignmentFlag.AlignLeft
                            | QtCore.Qt.AlignmentFlag.AlignVCenter,
                            symbol,
                        )
                        temp_rect = rect.adjusted(22, 0, 0, 0)
                    else:
                        temp_rect = rect

                    painter.setFont(self.formatter.info_font(size=12))
                    painter.drawText(
                        temp_rect,
                        QtCore.Qt.AlignmentFlag.AlignLeft
                        | QtCore.Qt.AlignmentFlag.AlignVCenter,
                        f"{data.temperature:.1f}°C",
                    )

                elif item_type == "playback":
                    if data != self._last_playback_title:
                        self._last_playback_title = data
                        self._playback_title_scroll_start_time = time.time()

                    painter.setFont(self.formatter.info_font(size=12))
                    painter.drawText(
                        rect,
                        QtCore.Qt.AlignmentFlag.AlignLeft
                        | QtCore.Qt.AlignmentFlag.AlignVCenter,
                        "\uf2eb",
                    )

                    self._draw_scrolling_text(
                        painter,
                        rect.adjusted(20, 0, -5, 0),
                        data,
                        self.formatter.info_font(size=12),
                        fg_color,
                        self._playback_title_scroll_start_time,
                    )

                elif item_type == "alarm":
                    painter.setFont(self.formatter.info_font(size=12))
                    painter.drawText(
                        rect,
                        QtCore.Qt.AlignmentFlag.AlignLeft
                        | QtCore.Qt.AlignmentFlag.AlignVCenter,
                        f"\uf49a {data.strftime('%H:%M')}",
                    )

                elif item_type == "volume":
                    painter.setFont(self.formatter.info_font(size=12))
                    painter.drawText(
                        rect,
                        QtCore.Qt.AlignmentFlag.AlignLeft
                        | QtCore.Qt.AlignmentFlag.AlignVCenter,
                        f"Vol: {int(data * 100)}%",
                    )

    def _paint_alarm_view(self, painter):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service:
            return

        alarm = service.current_alarm
        fg_color = QtGui.QColor(
            self.formatter.foreground_color(color_type=ColorType.INHEX)
        )
        painter.setPen(fg_color)

        # Header
        index = service.current_alarm_index + 1
        total = len(self.alarm_clock_context.config.alarm_definitions) + 1
        painter.setFont(self.formatter.info_font(size=10))
        painter.drawText(
            QtCore.QRect(10, 5, self.device.width - 20, 15),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"ALARM {index}/{total}",
        )

        # Time
        time_str = f"{alarm.hour:02d}:{alarm.min:02d}"
        painter.setFont(self.formatter.info_font(size=32))
        painter.drawText(
            QtCore.QRect(10, 20, 150, 40),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            time_str,
        )

        # Status
        status_icon = "\uf205" if alarm.is_active else "\uf204"
        painter.setFont(self.formatter.info_font(size=15))
        painter.drawText(
            QtCore.QRect(self.device.width - 60, 15, 40, 30),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            status_icon,
        )

        # Days
        days_str = "New Alarm"
        if alarm.id is not None:
            try:
                days_str = alarm.to_day_string()
                if len(days_str) > 15:
                    days_str = days_str[:12] + "..."
            except:
                days_str = "Invalid"
        painter.setFont(self.formatter.info_font(size=12))
        painter.drawText(
            QtCore.QRect(self.device.width - 110, 45, 100, 20),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignBottom,
            days_str,
        )

    def _paint_alarm_edit_view(self, painter):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        current_prop = service.property_to_edit
        fg_color = QtGui.QColor(
            self.formatter.foreground_color(color_type=ColorType.INHEX)
        )
        painter.setPen(fg_color)

        # Property Name
        prop_font_size = 18
        prop_name = ""
        if isinstance(current_prop, AlarmProperty):
            prop_name = current_prop.name.replace("_", " ")
        elif isinstance(current_prop, EditorAction):
            prop_name = current_prop.value.upper()

        if len(prop_name) > 15:
            prop_font_size = 15

        painter.setFont(self.formatter.info_font(size=prop_font_size))
        painter.drawText(
            QtCore.QRect(0, 10, self.device.width, 25),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            prop_name,
        )

        # Current Value Preview
        if isinstance(current_prop, AlarmProperty):
            val = service.editing_session.get_current_value()
            val_str = str(val)
            if current_prop == AlarmProperty.RECURRING:
                val_str = f"{len(val)} days"
            elif current_prop == AlarmProperty.ONETIME:
                val_str = self._format_date(val)
            elif current_prop == AlarmProperty.AUDIO_EFFECT:
                val_str = val.title() if val else "None"
            elif current_prop == AlarmProperty.AUDIO_EFFECT_VOLUME:
                val_str = f"{int(round(val*100, 0))}%"
            elif current_prop == AlarmProperty.VISUAL_EFFECT:
                val_str = "yes" if val else "no"

            painter.setFont(self.formatter.info_font(size=12))
            painter.drawText(
                QtCore.QRect(0, 35, self.device.width, 20),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                val_str,
            )

    def _paint_property_edit_view(self, painter):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        current_prop = service.property_to_edit
        current_val = service.editing_session.get_current_value()
        fg_color = QtGui.QColor(
            self.formatter.foreground_color(color_type=ColorType.INHEX)
        )
        painter.setPen(fg_color)

        # Property Name
        prop_name = (
            current_prop.name.replace("_", " ")
            if isinstance(current_prop, AlarmProperty)
            else ""
        )
        painter.setFont(self.formatter.info_font(size=10))
        painter.drawText(
            QtCore.QRect(0, 5, self.device.width, 15),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            f"SET {prop_name}",
        )

        # Value with arrows
        val_font_size = 18
        val_str = str(current_val)
        if current_prop == AlarmProperty.RECURRING:
            val_str = ",".join([d[:2] for d in current_val])
            val_font_size = 12
            if len(val_str) > 15:
                val_font_size = 8

        elif current_prop == AlarmProperty.ONETIME:
            val_str = self._format_date(current_val)
        elif current_prop == AlarmProperty.AUDIO_EFFECT:
            val_str = current_val.title() if current_val else "None"
        elif current_prop == AlarmProperty.AUDIO_EFFECT_VOLUME:
            val_str = f"{int(round(current_val*100, 0))}%"
        elif current_prop == AlarmProperty.HOUR or current_prop == AlarmProperty.MIN:
            val_str = f"{current_val:02d}"
        elif current_prop == AlarmProperty.VISUAL_EFFECT:
            val_str = "yes" if current_val else "no"

        painter.setFont(self.formatter.info_font(size=16))
        painter.drawText(
            QtCore.QRect(10, 25, 30, 35),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "\uf053",
        )  # Left
        painter.drawText(
            QtCore.QRect(self.device.width - 40, 25, 30, 35),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "\uf054",
        )  # Right

        painter.setFont(self.formatter.info_font(size=val_font_size))
        painter.drawText(
            QtCore.QRect(40, 25, self.device.width - 80, 35),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            val_str,
        )

    def _paint_day_picker_view(self, painter):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        day_picker = service.editing_session.day_picker_session
        if not day_picker:
            return

        fg_color = QtGui.QColor(
            self.formatter.foreground_color(color_type=ColorType.INHEX)
        )
        painter.setPen(fg_color)

        # Header
        painter.setFont(self.formatter.info_font(size=10))
        painter.drawText(
            QtCore.QRect(0, 2, self.device.width, 14),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "SELECT DAYS",
        )

        # Day cells + OK: 8 items across the display width
        items = [d.name[:2] for d in DayPickerSession.DAYS] + ["OK"]
        cell_width = self.device.width // len(items)
        cell_top = 16
        cell_height = self.device.height - cell_top

        for i, label in enumerate(items):
            x = i * cell_width
            cell_rect = QtCore.QRect(x, cell_top, cell_width, cell_height)

            is_cursor = day_picker.cursor == i
            is_ok = i == DayPickerSession.OK_INDEX
            is_active = (
                not is_ok and DayPickerSession.DAYS[i].name in day_picker.active_days
            )

            # Highlight cursor position
            if is_cursor:
                painter.fillRect(
                    cell_rect,
                    QtGui.QColor(
                        self.formatter.foreground_color(color_type=ColorType.INHEX)
                    ),
                )
                text_color = QtGui.QColor(
                    self.formatter.background_color(color_type=ColorType.INHEX)
                )
            else:
                text_color = fg_color

            painter.setPen(text_color)

            # Active indicator: toggle icon (fa-toggle-on/off) rotated 90° → vertical
            if not is_ok:
                toggle_char = "\uf204" if is_active else "\uf205"
                painter.save()
                painter.setFont(self.formatter.info_font(size=14))
                painter.setPen(text_color)
                cx = x + cell_width // 2
                cy = cell_top + 13
                painter.translate(cx, cy)
                painter.rotate(90)
                painter.drawText(
                    QtCore.QRect(-13, -14, 26, 26),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    toggle_char,
                )
                painter.restore()

            # Day abbreviation (below the symbol)
            painter.setPen(text_color)
            painter.setFont(self.formatter.info_font(size=10))
            painter.drawText(
                QtCore.QRect(x, cell_top + 32, cell_width, 14),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                label,
            )

            painter.setPen(fg_color)

    def _format_date(self, d) -> str:
        from datetime import timedelta

        if d is None:
            return "None"
        today = GeoLocation().now().date()
        if d == today:
            return "today"
        if d == today + timedelta(days=1):
            return "tomorrow"
        return d.strftime("%Y-%m-%d")

    def initialize_qt_app(self):
        QtCore.qInstallMessageHandler(qt_message_handler)
        self.app = QtGui.QGuiApplication([])
        logger.info("Qt Application initialized")

    def grab_widget_image(self) -> Image.Image:
        width = self.buffer_image.width()
        height = self.buffer_image.height()
        stride = self.buffer_image.bytesPerLine()
        ptr = self.buffer_image.bits()
        ptr.setsize(self.buffer_image.byteCount())
        return Image.frombytes("RGB", (width, height), ptr, "raw", "RGB", stride, 1)

    def refresh(self):
        self.formatter.update_formatter()
        self.display_content.is_scrolling = False

        bg_color = QtGui.QColor(
            self.formatter.background_color(color_type=ColorType.INHEX)
        )
        self.buffer_image.fill(bg_color)

        painter = QtGui.QPainter(self.buffer_image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

        self.paint(painter)
        painter.end()

        self.current_display_image = self.formatter.postprocess_image(
            self.grab_widget_image()
        )
        try:
            self.device.display(self.current_display_image)
            if isinstance(self.device, luma_dummy):
                self.current_display_image.save(
                    display_shot_file,
                    format="png",
                )
        except AssertionError:
            pass


if __name__ == "__main__":
    import argparse
    from luma.oled.device import ssd1322
    from luma.core.interface.serial import spi
    from luma.core.device import dummy
    import time

    parser = argparse.ArgumentParser("Display")
    parser.add_argument("-s", "--software", action="store_true")
    is_on_hardware = not parser.parse_args().software
    dev: luma_device

    if is_on_hardware:
        dev = ssd1322(serial_interface=spi(device=0, port=0))
    else:
        dev = dummy(height=64, width=256, mode="RGB")

    from utils.sound_device import TACSoundDevice

    c = Config()
    eb = EventBus()
    sd = TACSoundDevice()
    s = AlarmClockContext(config=c)
    pc = PlaybackContent(alarm_clock_context=s, sound_device=sd, event_bus=eb)
    pc.audio_stream = SpotifyStream()
    dc = DisplayContent(alarm_clock_context=s, playback_content=pc, event_bus=eb)
    dc.show_blink_segment = True
    df = DisplayFormatter(dc, s)
    d = Display(dev, dc, pc, df, s, eb)
    d.refresh()
    image = d.current_display_image

    # with canvas(dev) as draw:
    # 	draw.text((20, 20), "Hello World!", fill="white")

    if is_on_hardware:
        time.sleep(10)
    else:
        save_file = display_shot_file
        image.save(save_file, format="png")
