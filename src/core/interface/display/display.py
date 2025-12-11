import io
import logging
from timeit import timeit
import traceback
import time
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import Image

from PyQt5 import QtWidgets, QtCore, QtGui

from core.domain.events import (
    AlarmStoppedEvent,
    ForcedDisplayUpdateEvent,
)
from core.interface.display.display_events import (
    DisplayPlaybackUpdatedEvent,
    DisplayVolumeUpdatedEvent,
    DisplayNextAlarmUpdatedEvent,
    DisplayWeatherUpdatedEvent,
    DisplayBrightnessUpdatedEvent,
)
from core.domain.edit_mode import AlarmProperty, EditorAction
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


class ClockWidget(QtWidgets.QWidget):
    def __init__(self, hour_str, min_str, blink_char, show_blink, fg_color, font_obj):
        super().__init__()
        self.hour_str = hour_str
        self.min_str = min_str
        self.blink_char = blink_char
        self.show_blink = show_blink
        self.fg_color = QtGui.QColor(fg_color)
        self.font_obj = font_obj
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )

    def update_content(self, hour_str, min_str, show_blink, fg_color):
        self.hour_str = hour_str
        self.min_str = min_str
        self.show_blink = show_blink
        self.fg_color = QtGui.QColor(fg_color)
        self.update()

    def _calculate_layout(self, fm, overlap):
        x = 0
        # Hours
        for i, char in enumerate(self.hour_str):
            if i < len(self.hour_str) - 1:
                x += fm.width(char) - overlap
            else:
                x += fm.width(char)

        x += -15
        # Separator
        x += fm.width(self.blink_char)
        x += -10

        # Minutes
        for i, char in enumerate(self.min_str):
            if i < len(self.min_str) - 1:
                x += fm.width(char) - overlap
            else:
                x += fm.width(char)

        return x

    def minimumSizeHint(self):
        fm = QtGui.QFontMetrics(self.font_obj)
        overlap = 12
        width = self._calculate_layout(fm, overlap)
        return QtCore.QSize(width, fm.height() + 10)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

        painter.setFont(self.font_obj)
        fm = QtGui.QFontMetrics(self.font_obj)

        overlap = 12
        vertical_shift = 2
        x = 0
        # Center vertically
        base_y = int((self.height() + fm.ascent() - fm.descent()) / 2)

        h, s, v, a = self.fg_color.getHsv()
        white_color = self.fg_color
        # 16-level grayscale has steps of ~17 (255/15). Use the next darker level.
        gray_color = QtGui.QColor.fromHsv(h, s, max(17, v - 1 * 18), a)

        # Draw Hours
        for i, char in enumerate(self.hour_str):
            if i == 0:
                painter.setPen(white_color)
                y = base_y - vertical_shift
            else:
                painter.setPen(gray_color)
                y = base_y + vertical_shift

            painter.drawText(x, y, char)

            if i < len(self.hour_str) - 1:
                x += fm.width(char) - overlap
            else:
                x += fm.width(char)

        x += -15
        # Draw Separator
        sep_width = fm.width(self.blink_char)
        if self.show_blink:
            painter.setPen(white_color)
            painter.drawText(x, base_y, self.blink_char)

        x += sep_width
        x += -10

        # Draw Minutes
        for i, char in enumerate(self.min_str):
            if i == 0:
                painter.setPen(white_color)
                y = base_y - vertical_shift
            else:
                painter.setPen(gray_color)
                y = base_y + vertical_shift

            painter.drawText(x, y, char)

            if i < len(self.min_str) - 1:
                x += fm.width(char) - overlap
            else:
                x += fm.width(char)


class ScrollingLabel(QtWidgets.QWidget):
    def __init__(
        self,
        text,
        font_obj,
        color,
        start_time,
        display_content: DisplayContent,
        speed=30,
    ):
        super().__init__()
        self.text = text
        self.font_obj = font_obj
        self.color = QtGui.QColor(color)
        self.start_time = start_time
        self.display_content = display_content
        self.speed = speed
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )

    def update_color(self, color):
        self.color = QtGui.QColor(color)
        self.update()

    def update_content(self, text, start_time=None):
        self.text = text
        if start_time is not None:
            self.start_time = start_time
        self.update()

    def minimumSizeHint(self):
        fm = QtGui.QFontMetrics(self.font_obj)
        return QtCore.QSize(10, fm.height())

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

        painter.setFont(self.font_obj)
        painter.setPen(self.color)
        fm = QtGui.QFontMetrics(self.font_obj)
        text_width = fm.width(self.text)
        widget_width = self.width()

        # Center vertically
        # drawText(x, y, string) draws with baseline at y.
        # But drawText(rect, flags, string) handles alignment.

        if text_width <= widget_width:
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                self.text,
            )
        else:
            # DDD Note: Updating the ViewModel (DisplayContent) from the View (ScrollingLabel)
            # is acceptable within the Interface Layer to signal presentation requirements (refresh rate).
            self.display_content.is_scrolling = True

            elapsed = time.time() - self.start_time

            # Add a pause at the beginning
            pause_duration = 2.0
            if elapsed < pause_duration:
                offset = 0
            else:
                offset = (elapsed - pause_duration) * self.speed

            gap = 30
            total_cycle_width = text_width + gap

            current_offset = offset % total_cycle_width

            # Calculate y for baseline
            # rect().center().y() + fm.ascent()/2 - fm.descent()/2 roughly?
            # Or just use rect with alignment? No, manual x is needed.

            # Using drawText(x, y, text)
            # y is baseline.
            # widget height center:
            y = (self.height() + fm.ascent() - fm.descent()) // 2

            # Draw first instance
            x1 = -current_offset
            if x1 + text_width > 0:
                painter.drawText(int(x1), int(y), self.text)

            # Draw second instance if needed
            x2 = x1 + total_cycle_width
            if x2 < widget_width:
                painter.drawText(int(x2), int(y), self.text)


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

        self.widget = None
        self.current_layout_type = None

        # Widget references
        self.clock_widget = None
        self.weather_symbol_label = None
        self.weather_temp_label = None
        self.playback_symbol_label = None
        self.playback_label = None
        self.alarm_symbol_label = None
        self.alarm_label = None
        self.vol_label = None
        self.wifi_label = None

        # Alarm View Widgets
        self.av_header_label = None
        self.av_time_label = None
        self.av_status_label = None
        self.av_days_label = None

        # Edit View Widgets
        self.ev_prop_label = None
        self.ev_val_label = None

        # Property Edit View Widgets
        self.pev_header_label = None
        self.pev_val_label = None

        self.event_bus.on(ForcedDisplayUpdateEvent)(
            self._handle_forced_display_update_event
        )
        self.event_bus.on(AlarmStoppedEvent)(self._alarm_stopped)
        self.event_bus.on(DisplayPlaybackUpdatedEvent)(self.on_display_playback_changed)
        self.event_bus.on(DisplayVolumeUpdatedEvent)(self.on_display_volume_changed)
        self.event_bus.on(DisplayNextAlarmUpdatedEvent)(self.on_display_alarm_changed)
        self.event_bus.on(DisplayWeatherUpdatedEvent)(self.on_display_weather_changed)
        self.event_bus.on(DisplayBrightnessUpdatedEvent)(
            self.on_display_brightness_changed
        )

    def _alarm_stopped(self, _: AlarmStoppedEvent):
        self.device.hide()
        self.device.show()
        self.safe_refresh_display()

    def _handle_forced_display_update_event(self, _: ForcedDisplayUpdateEvent = None):
        self.safe_refresh_display()

    def safe_refresh_display(self):

        try:
            self.refresh()
        except Exception as e:
            logger.error("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception!\n({e})", fill="white")

    def _setup_default_dimmed_view(self, layout: QtWidgets.QHBoxLayout):
        # Container
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)

        # Clock
        self.clock_label = QtWidgets.QLabel("")
        self.clock_label.setFont(
            self.formatter.clock_font(size=18, weight=QtGui.QFont.Weight.Light)
        )
        self.clock_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )
        container_layout.addWidget(self.clock_label)

        # Info Stack
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        info_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # Next Alarm
        self.alarm_label = QtWidgets.QLabel("")
        self.alarm_label.setFont(self.formatter.info_font(size=12))
        self.alarm_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.alarm_label)

        # WiFi
        self.wifi_label = QtWidgets.QLabel("")
        self.wifi_label.setFont(self.formatter.info_font(size=14))
        self.wifi_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.wifi_label)

        container_layout.addLayout(info_layout)

        layout.addWidget(
            container,
            alignment=QtCore.Qt.AlignmentFlag.AlignTop
            | QtCore.Qt.AlignmentFlag.AlignLeft,
        )
        layout.addStretch()

    def _update_default_dimmed_view(self):
        now = GeoLocation().now()
        day = now.day

        # Screensaver logic: shift content based on day of month
        x_offset = day * 3
        y_offset = (day % 5) * 4

        self.widget.layout().setContentsMargins(x_offset, y_offset, 0, 0)

        # Clock
        clock_string = self.formatter.format_dseg7_clock_string(
            now, self.display_content.show_blink_segment
        )
        self.clock_label.setText(clock_string)

        # Next Alarm
        if (
            self.display_content.has_next_alarm()
            and self.display_content.next_alarm_info.minutes_until_alarm()
            <= self.display_content.alarm_clock_context.config.alarm_preview_hours * 60
        ):
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = self.formatter.format_clock_string(alarm_time)
            self.alarm_label.setText(f"\uf49a {alarm_text}")
            self.alarm_label.show()
        else:
            self.alarm_label.hide()

        # WiFi
        is_online = self.display_content.get_is_online()
        no_wifi_symbol = "\U000f05aa"
        wifi_text = "" if is_online else no_wifi_symbol
        self.wifi_label.setText(wifi_text)

    def _setup_default_normal_view(self, layout: QtWidgets.QHBoxLayout):
        layout.addSpacing(10)

        # Clock Widget
        self.clock_widget = ClockWidget(
            "00", "00", ":", True, "#FFFFFF", self.formatter.clock_font(size=42)
        )
        layout.addWidget(self.clock_widget, stretch=3)

        # Vertical Line
        self.line = QtWidgets.QWidget()
        self.line.setFixedWidth(1)
        layout.addWidget(self.line)
        layout.addSpacing(10)

        # Info Stack
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        info_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # 1. Weather
        self.weather_container = QtWidgets.QWidget()
        weather_layout = QtWidgets.QHBoxLayout(self.weather_container)
        weather_layout.setContentsMargins(0, 0, 0, 0)
        weather_layout.setSpacing(5)
        weather_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        self.weather_symbol_label = QtWidgets.QLabel("")
        self.weather_symbol_label.setFont(self.formatter.weather_font(size=16))
        weather_layout.addWidget(self.weather_symbol_label)

        self.weather_temp_label = QtWidgets.QLabel("")
        self.weather_temp_label.setFont(self.formatter.info_font(size=12))
        weather_layout.addWidget(self.weather_temp_label)

        info_layout.addWidget(self.weather_container)

        # 2. Playback
        self.playback_container = QtWidgets.QWidget()
        playback_layout = QtWidgets.QHBoxLayout(self.playback_container)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(5)
        playback_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        self.playback_symbol_label = QtWidgets.QLabel("\uf2eb")
        self.playback_symbol_label.setFont(self.formatter.info_font(size=16))
        playback_layout.addWidget(self.playback_symbol_label)

        self.playback_label = ScrollingLabel(
            "",
            self.formatter.info_font(size=12),
            "#FFFFFF",
            0,
            self.display_content,
        )
        playback_layout.addWidget(self.playback_label)

        info_layout.addWidget(self.playback_container)

        # 3. Next Alarm
        self.alarm_container = QtWidgets.QWidget()
        alarm_layout = QtWidgets.QHBoxLayout(self.alarm_container)
        alarm_layout.setContentsMargins(0, 0, 0, 0)
        alarm_layout.setSpacing(5)
        alarm_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        self.alarm_symbol_label = QtWidgets.QLabel("\uf49a")
        self.alarm_symbol_label.setFont(self.formatter.info_font(size=12))
        alarm_layout.addWidget(self.alarm_symbol_label)

        self.alarm_label = QtWidgets.QLabel("")
        self.alarm_label.setFont(self.formatter.info_font(size=12))
        alarm_layout.addWidget(self.alarm_label)

        info_layout.addWidget(self.alarm_container)

        # 4. Volume
        self.vol_label = QtWidgets.QLabel("")
        self.vol_label.setFont(self.formatter.info_font(size=12))
        self.vol_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.vol_label)

        layout.addLayout(info_layout, stretch=1)

    def _update_default_normal_view(self):
        self._update_clock_only()
        self.on_display_alarm_changed()
        self.on_display_playback_changed()
        self.on_display_volume_changed()
        self.on_display_weather_changed()

    def _update_clock_only(self):
        # Clock
        fmt = self.alarm_clock_context.config.clock_format_string
        parts = fmt.split("<blinkSegment>")
        if len(parts) == 2:
            hour_fmt = parts[0]
            min_fmt = parts[1]
        else:
            hour_fmt = "%H"
            min_fmt = "%M"

        now = GeoLocation().now()
        hour_str = now.strftime(hour_fmt)
        minute_str = now.strftime(min_fmt)
        fg_color = self.formatter.foreground_color(color_type=ColorType.INHEX)

        self.clock_widget.update_content(
            hour_str, minute_str, self.display_content.show_blink_segment, fg_color
        )

        # Line color
        self.line.setStyleSheet(f"background-color: {fg_color};")

    def on_display_weather_changed(self, _=None):
        if self.current_layout_type != "DEFAULT_NORMAL":
            return

        # Weather
        weather = self.display_content.current_weather
        if weather and weather.temperature is not None:
            symbol = weather.code.to_character() if weather.code else None
            if symbol:
                self.weather_symbol_label.setText(symbol)
                self.weather_symbol_label.show()
            else:
                self.weather_symbol_label.hide()

            self.weather_temp_label.setText(f"{weather.temperature:.1f}°C")
            self.weather_container.show()
        else:
            self.weather_container.hide()

    def on_display_playback_changed(self, _=None):
        if self.current_layout_type != "DEFAULT_NORMAL":
            return

        # Playback
        playback_title = self.display_content.current_playback_title()
        if playback_title:
            if playback_title != self._last_playback_title:
                self._last_playback_title = playback_title
                self._playback_title_scroll_start_time = time.time()

            self.playback_label.update_content(
                playback_title, self._playback_title_scroll_start_time
            )
            self.playback_container.show()
        else:
            self.playback_container.hide()

    def on_display_alarm_changed(self, _=None):
        if self.current_layout_type != "DEFAULT_NORMAL":
            return

        # Next Alarm
        if (
            self.display_content.has_next_alarm()
            and self.display_content.next_alarm_info.minutes_until_alarm()
            <= self.display_content.alarm_clock_context.config.alarm_preview_hours * 60
        ):
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = alarm_time.strftime("%H:%M")
            self.alarm_label.setText(alarm_text)
            self.alarm_container.show()
        else:
            self.alarm_container.hide()

    def on_display_volume_changed(self, _=None):
        if self.current_layout_type != "DEFAULT_NORMAL":
            return

        # Volume
        if self.display_content.show_volume_meter:
            vol = self.display_content.current_volume()
            self.vol_label.setText(f"Vol: {int(vol * 100)}%")
            self.vol_label.show()
        else:
            self.vol_label.hide()

    def on_display_brightness_changed(self, _=None):
        # This affects colors, so we might need to update everything or just colors.
        # For simplicity, trigger a full content update for the current layout.
        self._update_content(self.current_layout_type)

    def _draw_default_view(self, layout: QtWidgets.QHBoxLayout):
        if self.formatter.be_gloomy():
            self._draw_dimmed_content(layout)
        else:
            self._draw_normal_content(layout)

    def _setup_alarm_view(self, layout: QtWidgets.QHBoxLayout):
        # Main Container
        container = QtWidgets.QWidget()
        # Use a grid layout for better control
        grid = QtWidgets.QGridLayout(container)
        grid.setContentsMargins(10, 5, 10, 5)

        # Row 0: Header (Alarm Index)
        self.av_header_label = QtWidgets.QLabel("")
        self.av_header_label.setFont(self.formatter.info_font(size=10))
        grid.addWidget(
            self.av_header_label, 0, 0, 1, 2, QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # Row 1: Time (Big)
        self.av_time_label = QtWidgets.QLabel("")
        self.av_time_label.setFont(self.formatter.info_font(size=32))
        grid.addWidget(
            self.av_time_label, 1, 0, 2, 1, QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # Row 1, Col 1: Active Status
        self.av_status_label = QtWidgets.QLabel("")
        self.av_status_label.setFont(self.formatter.info_font(size=20))
        grid.addWidget(self.av_status_label, 1, 1, QtCore.Qt.AlignmentFlag.AlignRight)

        # Row 2, Col 1: Days
        self.av_days_label = QtWidgets.QLabel("")
        self.av_days_label.setFont(self.formatter.info_font(size=12))
        grid.addWidget(self.av_days_label, 2, 1, QtCore.Qt.AlignmentFlag.AlignRight)

        layout.addWidget(container)

    def _update_alarm_view(self):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service:
            return

        alarm = service.current_alarm

        # Header
        index = service.current_alarm_index + 1
        total = len(self.alarm_clock_context.config.alarm_definitions) + 1
        self.av_header_label.setText(f"ALARM {index}/{total}")

        # Time
        time_str = f"{alarm.hour:02d}:{alarm.min:02d}"
        self.av_time_label.setText(time_str)

        # Status
        status_icon = "\uf205" if alarm.is_active else "\uf204"  # Toggle On/Off
        self.av_status_label.setText(status_icon)

        # Days
        days_str = "New Alarm"
        if alarm.id is not None:
            try:
                days_str = alarm.to_day_string()
                if len(days_str) > 15:
                    days_str = days_str[:12] + "..."
            except:
                days_str = "Invalid"
        self.av_days_label.setText(days_str)

    def _setup_alarm_edit_view(self, layout: QtWidgets.QHBoxLayout):
        container = QtWidgets.QWidget()
        v_layout = QtWidgets.QVBoxLayout(container)
        v_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Property Name
        self.ev_prop_label = QtWidgets.QLabel("")
        self.ev_prop_label.setFont(self.formatter.info_font(size=18))
        self.ev_prop_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        v_layout.addWidget(self.ev_prop_label)

        # Current Value Preview
        self.ev_val_label = QtWidgets.QLabel("")
        self.ev_val_label.setFont(self.formatter.info_font(size=12))
        self.ev_val_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        v_layout.addWidget(self.ev_val_label)

        layout.addWidget(container)

    def _update_alarm_edit_view(self):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        current_prop = service.property_to_edit

        # Property Name
        prop_name = ""
        if isinstance(current_prop, AlarmProperty):
            prop_name = current_prop.name.replace("_", " ")
        elif isinstance(current_prop, EditorAction):
            prop_name = current_prop.value.upper()
        self.ev_prop_label.setText(prop_name)

        # Current Value Preview
        if isinstance(current_prop, AlarmProperty):
            val = service.editing_session.get_current_value()
            val_str = str(val)
            # Format specific values
            if current_prop == AlarmProperty.RECURRING:
                # val is list of strings
                val_str = f"{len(val)} days"
            elif current_prop == AlarmProperty.AUDIO_EFFECT:
                val_str = val.title() if val else "None"

            self.ev_val_label.setText(val_str)
            self.ev_val_label.show()
        else:
            self.ev_val_label.hide()

    def _setup_property_edit_view(self, layout: QtWidgets.QHBoxLayout):
        container = QtWidgets.QWidget()
        v_layout = QtWidgets.QVBoxLayout(container)
        v_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Property Name
        self.pev_header_label = QtWidgets.QLabel("")
        self.pev_header_label.setFont(self.formatter.info_font(size=10))
        self.pev_header_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        v_layout.addWidget(self.pev_header_label)

        # Value with arrows
        h_layout = QtWidgets.QHBoxLayout()
        h_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        left_arrow = QtWidgets.QLabel("\uf053")  # Chevron Left
        left_arrow.setFont(self.formatter.info_font(size=16))
        h_layout.addWidget(left_arrow)

        self.pev_val_label = QtWidgets.QLabel("")
        self.pev_val_label.setFont(self.formatter.info_font(size=18))
        h_layout.addWidget(self.pev_val_label)

        right_arrow = QtWidgets.QLabel("\uf054")  # Chevron Right
        right_arrow.setFont(self.formatter.info_font(size=16))
        h_layout.addWidget(right_arrow)

        v_layout.addLayout(h_layout)
        layout.addWidget(container)

    def _update_property_edit_view(self):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        current_prop = service.property_to_edit
        current_val = service.editing_session.get_current_value()

        # Property Name
        prop_name = (
            current_prop.name.replace("_", " ")
            if isinstance(current_prop, AlarmProperty)
            else ""
        )
        self.pev_header_label.setText(f"SET {prop_name}")

        # Value
        val_str = str(current_val)
        # Formatting
        if current_prop == AlarmProperty.RECURRING:
            val_str = ", ".join([d[:3] for d in current_val])
        elif current_prop == AlarmProperty.AUDIO_EFFECT:
            val_str = current_val.title() if current_val else "None"
        elif current_prop == AlarmProperty.HOUR or current_prop == AlarmProperty.MIN:
            val_str = f"{current_val:02d}"

        self.pev_val_label.setText(f" {val_str} ")

    def initialize_qt_app(self):
        self.app = QtWidgets.QApplication([])

    def update_ui(self):
        self.formatter.update_formatter()
        # Reset scrolling state; widgets will set it to True if they need high refresh rate
        self.display_content.is_scrolling = False

        mode = (
            self.alarm_clock_context.mode_coordinator.current_mode_name
            if self.alarm_clock_context.mode_coordinator
            else ModeName.DEFAULT
        )

        layout_type = mode
        if mode == ModeName.DEFAULT:
            if self.formatter.be_gloomy():
                layout_type = "DEFAULT_DIMMED"
            else:
                layout_type = "DEFAULT_NORMAL"

        if self.current_layout_type != layout_type:
            self._setup_layout(layout_type)
            self.current_layout_type = layout_type

            # On layout change, perform a full update of the new view
            if layout_type == "DEFAULT_NORMAL":
                self._update_default_normal_view()

        self._update_content(layout_type)

        self.widget.adjustSize()

    def grab_widget_image(self) -> Image.Image:
        pixmap = self.widget.grab()

        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "BMP")

        pil_image = Image.open(io.BytesIO(buffer.data())).convert("L")
        return pil_image

    def grab_widget_image_fail(self) -> Image.Image:
        # Optimized: Convert QImage directly to PIL Image avoiding PNG encoding/decoding
        qimage = self.widget.grab().toImage()
        qimage = qimage.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
        width = qimage.width()
        height = qimage.height()
        stride = qimage.bytesPerLine()

        ptr = qimage.bits()
        ptr.setsize(qimage.byteCount())

        # Create PIL Image from raw bytes (copying to avoid segfaults when qimage is collected)
        # We convert to 'L' (grayscale) immediately as the rest of the pipeline expects it
        # and it reduces memory usage.
        return Image.frombytes("L", (width, height), ptr, "raw", "L", stride, 1)

    def refresh(self):
        logger.debug("update_ui: %sms", timeit(self.update_ui, number=1) * 1000)
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
        except AssertionError as e:
            pass

    def _setup_layout(self, layout_type):
        self.widget = QtWidgets.QFrame()
        self.widget.setFixedSize(self.device.width, self.device.height)

        layout = QtWidgets.QHBoxLayout(self.widget)
        layout.setContentsMargins(10, 0, 5, 0)
        layout.setSpacing(0)

        if layout_type == "DEFAULT_NORMAL":
            self._setup_default_normal_view(layout)
        elif layout_type == "DEFAULT_DIMMED":
            self._setup_default_dimmed_view(layout)
        elif layout_type == ModeName.ALARM_VIEW:
            self._setup_alarm_view(layout)
        elif layout_type == ModeName.ALARM_EDIT:
            self._setup_alarm_edit_view(layout)
        elif layout_type == ModeName.PROPERTY_EDIT:
            self._setup_property_edit_view(layout)

    def _update_content(self, layout_type):
        if not self.widget:
            return
        fg_color = self.formatter.foreground_color(color_type=ColorType.INHEX)
        bg_color = self.formatter.background_color(color_type=ColorType.INHEX)

        self.widget.setStyleSheet(
            f"background-color: {bg_color}; color: {fg_color}; border: none;"
        )

        if layout_type == "DEFAULT_NORMAL":
            # Optimized: Only update clock in the loop, other elements are event-driven
            self._update_clock_only()
            self.playback_label.update_color(fg_color)
            # We still need to update scrolling text if active
            if self.display_content.is_scrolling:
                self.on_display_playback_changed()
        elif layout_type == "DEFAULT_DIMMED":
            self._update_default_dimmed_view()
        elif layout_type == ModeName.ALARM_VIEW:
            self._update_alarm_view()
        elif layout_type == ModeName.ALARM_EDIT:
            self._update_alarm_edit_view()
        elif layout_type == ModeName.PROPERTY_EDIT:
            self._update_property_edit_view()


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
        dev = dummy(height=64, width=256, mode="1")

    c = Config()
    s = AlarmClockContext(c=c)
    pc = PlaybackContent(alarm_clock_context=s)
    pc.audio_stream = SpotifyStream()
    dc = DisplayContent(alarm_clock_context=s, playback_content=pc)
    dc.show_blink_segment = True
    d = Display(dev, dc, pc, s)
    d.refresh()
    image = d.current_display_image

    # with canvas(dev) as draw:
    # 	draw.text((20, 20), "Hello World!", fill="white")

    if is_on_hardware:
        time.sleep(10)
    else:
        save_file = display_shot_file
        image.save(save_file, format="png")
