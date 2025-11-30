import io
import logging
import traceback
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import Image

from PyQt5 import QtWidgets, QtCore, QtGui

from core.domain.events import (
    ForcedDisplayUpdateEvent,
)
from core.domain.model import (
    AlarmClockContext,
    Config,
    DisplayContentProvider,
    Mode,
    PlaybackContent,
    SpotifyStream,
)
from core.domain.mode_coordinator import ModeName
from core.interface.display.display_content import DisplayContent
from core.infrastructure.event_bus import EventBus
from core.interface.display.format import ColorType, DisplayFormatter

from utils.geolocation import GeoLocation
from utils.drawing import PresentationFont

from resources.resources import display_shot_file

logger = logging.getLogger("tac.display")


class ClockWidget(QtWidgets.QWidget):
    def __init__(
        self, hour_str, min_str, blink_char, show_blink, fg_color, font_family
    ):
        super().__init__()
        self.hour_str = hour_str
        self.min_str = min_str
        self.blink_char = blink_char
        self.show_blink = show_blink
        self.fg_color = QtGui.QColor(fg_color)
        self.font_family = font_family
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )

    def _calculate_layout(self, fm, overlap):
        x = 0
        # Hours
        for i, char in enumerate(self.hour_str):
            if i < len(self.hour_str) - 1:
                x += fm.width(char) - overlap
            else:
                x += fm.width(char)

        # Separator
        x += fm.width(self.blink_char)

        # Minutes
        for i, char in enumerate(self.min_str):
            if i < len(self.min_str) - 1:
                x += fm.width(char) - overlap
            else:
                x += fm.width(char)

        return x

    def minimumSizeHint(self):
        font = QtGui.QFont(self.font_family, 42, QtGui.QFont.Bold)
        fm = QtGui.QFontMetrics(font)
        overlap = 12
        width = self._calculate_layout(fm, overlap)
        return QtCore.QSize(width, fm.height() + 10)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

        font = QtGui.QFont(self.font_family, 42, QtGui.QFont.Bold)
        painter.setFont(font)
        fm = QtGui.QFontMetrics(font)

        overlap = 12
        vertical_shift = 2
        x = 0
        # Center vertically
        base_y = int((self.height() + fm.ascent() - fm.descent()) / 2)

        h, s, v, a = self.fg_color.getHsv()
        white_color = self.fg_color
        # 16-level grayscale has steps of ~17 (255/15). Use the next darker level.
        gray_color = QtGui.QColor.fromHsv(h, s, max(17, v - 2 * 18), a)

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


class Display(DisplayContentProvider):

    device: luma_device
    display_content: DisplayContent
    roboto_font_family: str
    nerd_font_family: str
    weather_font_family: str

    def __init__(
        self,
        device: luma_device,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        alarm_clock_context: AlarmClockContext,
        event_bus: EventBus = None,
    ) -> None:
        self.device = device
        logger.info("device mode: %s", self.device.mode)
        self.display_content = display_content
        self.playback_content = playback_content
        self.alarm_clock_context = alarm_clock_context
        self.event_bus = event_bus
        self.formatter = DisplayFormatter(
            self.display_content, self.alarm_clock_context
        )
        self.initialize_qt_app()
        self.event_bus.on(ForcedDisplayUpdateEvent)(self._forced_update)

    def _forced_update(self, _: ForcedDisplayUpdateEvent):
        try:
            self.refresh()
        except Exception as e:
            logger.warning("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception! ({e})", fill="white")

    def _draw_dimmed_content(self, layout: QtWidgets.QHBoxLayout):
        now = GeoLocation().now()
        day = now.day

        # Screensaver logic: shift content based on day of month
        x_offset = day * 3
        y_offset = (day % 5) * 4

        layout.setContentsMargins(x_offset, y_offset, 0, 0)

        # Container
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)

        # Clock
        clock_string = self.formatter.format_clock_string(
            now, self.display_content.show_blink_segment
        )
        clock_label = QtWidgets.QLabel(clock_string)
        font_family = self.roboto_font_family
        clock_label.setFont(QtGui.QFont(font_family, 20, QtGui.QFont.Normal))
        clock_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )
        container_layout.addWidget(clock_label)

        # Info Stack
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        info_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # Next Alarm
        if self.display_content.next_alarm_info.has_alarm():
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = alarm_time.strftime("%H:%M")
            alarm_label = QtWidgets.QLabel(f"\uf49a {alarm_text}")
            font_family = self.nerd_font_family
            alarm_label.setFont(QtGui.QFont(font_family, 14))
            alarm_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            info_layout.addWidget(alarm_label)

        # WiFi
        is_online = self.display_content.get_is_online()
        # Use Link (\uf0c1) for online, Broken Link (\uf127) for offline
        wifi_text = "" if is_online else "!"
        wifi_label = QtWidgets.QLabel(wifi_text)

        font_family = self.nerd_font_family
        wifi_label.setFont(QtGui.QFont(font_family, 14))

        wifi_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(wifi_label)

        container_layout.addLayout(info_layout)

        layout.addWidget(
            container,
            alignment=QtCore.Qt.AlignmentFlag.AlignTop
            | QtCore.Qt.AlignmentFlag.AlignLeft,
        )
        layout.addStretch()

    def _draw_normal_content(self, layout: QtWidgets.QHBoxLayout):
        # --- Left: Clock ---
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

        blink_char = self.alarm_clock_context.config.blink_segment

        # Get current foreground color
        fg_color = self.formatter.foreground_color(color_type=ColorType.INHEX)

        clock_widget = ClockWidget(
            hour_str,
            minute_str,
            blink_char,
            self.display_content.show_blink_segment,
            fg_color,
            font_family=self.roboto_font_family,
        )
        layout.addWidget(clock_widget, stretch=3)

        # Vertical Line
        line = QtWidgets.QWidget()
        line.setFixedWidth(1)
        line.setStyleSheet(f"background-color: {fg_color};")
        layout.addWidget(line)
        layout.addSpacing(10)

        # --- Right: Info Stack ---
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        info_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # 1. Weather
        weather = self.display_content.current_weather
        if weather:
            temp = weather.temperature if weather is not None else None
            if temp is not None:
                weather_container = QtWidgets.QWidget()
                weather_layout = QtWidgets.QHBoxLayout(weather_container)
                weather_layout.setContentsMargins(0, 0, 0, 0)
                weather_layout.setSpacing(5)
                weather_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

                symbol = weather.code.to_character() if weather.code else None
                if symbol:
                    symbol_label = QtWidgets.QLabel(symbol)
                    font_family = self.weather_font_family
                    symbol_label.setFont(QtGui.QFont(font_family, 16))
                    weather_layout.addWidget(symbol_label)

                weather_label = QtWidgets.QLabel(f"{temp:.1f}°C")
                font_family = self.nerd_font_family
                weather_label.setFont(QtGui.QFont(font_family, 12))
                weather_layout.addWidget(weather_label)

                info_layout.addWidget(weather_container)

        # 3. Playback
        playback_title = self.display_content.current_playback_title()
        if playback_title:
            if len(playback_title) > 12:
                playback_title = playback_title[:10] + "..."

            playback_container = QtWidgets.QWidget()
            playback_layout = QtWidgets.QHBoxLayout(playback_container)
            playback_layout.setContentsMargins(0, 0, 0, 0)
            playback_layout.setSpacing(5)
            playback_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

            playback_symbol = QtWidgets.QLabel("\uf2eb")
            font_family = self.nerd_font_family
            playback_symbol.setFont(QtGui.QFont(font_family, 16))
            playback_layout.addWidget(playback_symbol)

            playback_label = QtWidgets.QLabel(playback_title)
            playback_label.setFont(QtGui.QFont(font_family, 12))
            playback_layout.addWidget(playback_label)

            info_layout.addWidget(playback_container)

        # 3. Next Alarm
        if self.display_content.next_alarm_info.has_alarm():
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = alarm_time.strftime("%H:%M")

            alarm_container = QtWidgets.QWidget()
            alarm_layout = QtWidgets.QHBoxLayout(alarm_container)
            alarm_layout.setContentsMargins(0, 0, 0, 0)
            alarm_layout.setSpacing(5)
            alarm_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

            alarm_symbol = QtWidgets.QLabel("\uf49a")
            font_family = self.nerd_font_family
            alarm_symbol.setFont(QtGui.QFont(font_family, 20))
            alarm_layout.addWidget(alarm_symbol)

            alarm_label = QtWidgets.QLabel(alarm_text)
            alarm_label.setFont(QtGui.QFont(font_family, 12))
            alarm_layout.addWidget(alarm_label)

            info_layout.addWidget(alarm_container)
        # 4. Volume
        if self.display_content.show_volume_meter:
            vol = self.display_content.current_volume()
            vol_label = QtWidgets.QLabel(f"Vol: {int(vol * 100)}%")
            font_family = self.nerd_font_family
            vol_label.setFont(QtGui.QFont(font_family, 12, QtGui.QFont.Bold))
            vol_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            info_layout.addWidget(vol_label)

        layout.addLayout(info_layout, stretch=1)

    def _draw_default_view(self, layout: QtWidgets.QHBoxLayout):
        if (
            False
            or not self.display_content.room_brightness.is_highly_dimmed()
            or self.playback_content.playback_mode != Mode.Idle
        ):
            self._draw_normal_content(layout)
        else:
            self._draw_dimmed_content(layout)

    def _draw_alarm_view(self, layout: QtWidgets.QHBoxLayout):
        # Placeholder for Alarm View Mode
        pass

    def _draw_alarm_edit_view(self, layout: QtWidgets.QHBoxLayout):
        # Placeholder for Alarm Edit Mode
        pass

    def _draw_property_edit_view(self, layout: QtWidgets.QHBoxLayout):
        # Placeholder for Property Edit Mode
        pass

    def initialize_qt_app(self):
        self.app = QtWidgets.QApplication([])

        id = QtGui.QFontDatabase.addApplicationFont(PresentationFont.weather_font)
        if id != -1:
            families = QtGui.QFontDatabase.applicationFontFamilies(id)
            if families:
                self.weather_font_family = families[0]
        else:
            logger.error(
                f"Failed to load weather font from {PresentationFont.weather_font}"
            )

        id_nerd = QtGui.QFontDatabase.addApplicationFont(PresentationFont.default_font)
        if id_nerd != -1:
            families = QtGui.QFontDatabase.applicationFontFamilies(id_nerd)
            if families:
                self.nerd_font_family = families[0]

        id_roboto = QtGui.QFontDatabase.addApplicationFont(PresentationFont.roboto_font)
        if id_roboto != -1:
            families = QtGui.QFontDatabase.applicationFontFamilies(id_roboto)
            if families:
                self.roboto_font_family = families[0]

    def draw_widget(self) -> Image.Image:
        self.formatter.update_formatter()
        self.widget = QtWidgets.QFrame()
        self.widget.setFixedSize(self.device.width, self.device.height)

        fg_color = self.formatter.foreground_color(color_type=ColorType.INHEX)
        bg_color = self.formatter.background_color(color_type=ColorType.INHEX)

        self.widget.setStyleSheet(
            f"background-color: {bg_color}; color: {fg_color}; border: none;"
        )

        # Main Layout
        layout = QtWidgets.QHBoxLayout(self.widget)
        layout.setContentsMargins(10, 0, 5, 0)
        layout.setSpacing(0)

        mode = (
            self.alarm_clock_context.mode_coordinator.current_mode_name
            if self.alarm_clock_context.mode_coordinator
            else ModeName.DEFAULT
        )

        if mode == ModeName.DEFAULT:
            self._draw_default_view(layout)
        elif mode == ModeName.ALARM_VIEW:
            self._draw_alarm_view(layout)
        elif mode == ModeName.ALARM_EDIT:
            self._draw_alarm_edit_view(layout)
        elif mode == ModeName.PROPERTY_EDIT:
            self._draw_property_edit_view(layout)

        self.widget.adjustSize()

        pixmap = self.widget.grab()

        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")

        pil_image = Image.open(io.BytesIO(buffer.data()))
        return pil_image

    def refresh(self):
        logger.debug("refreshing display...")
        start_time = GeoLocation().now()
        self.current_display_image = self.draw_widget()
        self.device.display(self.current_display_image)
        if isinstance(self.device, luma_dummy):
            self.current_display_image.save(
                display_shot_file,
                format="png",
            )

        logger.debug(
            "refreshed display in %dms",
            (GeoLocation().now() - start_time).total_seconds() * 1000,
        )


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
