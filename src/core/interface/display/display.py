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
    PlaybackContent,
    SpotifyStream,
)
from core.interface.display.display_content import DisplayContent
from core.infrastructure.event_bus import EventBus
from core.interface.display.format import ColorType, DisplayFormatter

from utils.geolocation import GeoLocation
from utils.drawing import PresentationFont

from resources.resources import display_shot_file

logger = logging.getLogger("tac.display")


class ClockWidget(QtWidgets.QWidget):
    def __init__(
        self,
        hour_str,
        min_str,
        blink_char,
        show_blink,
        fg_color,
        font_family="Roboto Mono",
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
        gray_color = QtGui.QColor.fromHsv(h, s, int(v * 0.6), a)

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

        # Draw Separator
        sep_width = fm.width(self.blink_char)
        if self.show_blink:
            painter.setPen(white_color)
            painter.drawText(x, base_y, self.blink_char)

        x += sep_width

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
        self.app = QtWidgets.QApplication([])
        self.event_bus.on(ForcedDisplayUpdateEvent)(self._forced_update)

    def _forced_update(self, _: ForcedDisplayUpdateEvent):
        try:
            self.refresh()
        except Exception as e:
            logger.warning("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception! ({e})", fill="white")

    def _draw_dimmed_content(self, layout: QtWidgets.QHBoxLayout):
        # Clock
        clock_string = self.formatter.format_clock_string(
            GeoLocation().now(), self.display_content.show_blink_segment
        )
        clock_label = QtWidgets.QLabel(clock_string)
        clock_label.setFont(QtGui.QFont("Roboto Mono", 20, QtGui.QFont.Normal))
        clock_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(clock_label, stretch=1)

        # Info Stack
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 5, 0, 5)
        info_layout.setSpacing(0)
        info_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight
        )

        # Next Alarm
        if self.display_content.next_alarm_info.has_alarm():
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = alarm_time.strftime("%H:%M")
            alarm_label = QtWidgets.QLabel(f"🔔 {alarm_text}")
            alarm_label.setFont(QtGui.QFont("Arial", 10))
            alarm_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            info_layout.addWidget(alarm_label)

        # WiFi
        is_online = self.display_content.get_is_online()
        wifi_text = "\uf1eb" if is_online else "\uf06a"
        wifi_label = QtWidgets.QLabel(wifi_text)
        
        font_family = getattr(self, "nerd_font_family", "Monospace")
        wifi_label.setFont(QtGui.QFont(font_family, 14))
        
        wifi_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        info_layout.addWidget(wifi_label)

        layout.addLayout(info_layout, stretch=1)

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
        )
        layout.addWidget(clock_widget, stretch=3)

        # --- Right: Info Stack ---
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 5, 0, 5)
        info_layout.setSpacing(0)
        info_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight
        )

        # 1. Next Alarm
        if self.display_content.next_alarm_info.has_alarm():
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = alarm_time.strftime("%H:%M")
            alarm_label = QtWidgets.QLabel(f"🔔 {alarm_text}")
            alarm_label.setFont(QtGui.QFont("Arial", 10))
            alarm_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            info_layout.addWidget(alarm_label)

        # 2. Weather
        weather = self.display_content.current_weather
        if weather:
            temp = getattr(weather, "temperature", None)
            if temp is not None:
                weather_container = QtWidgets.QWidget()
                weather_layout = QtWidgets.QHBoxLayout(weather_container)
                weather_layout.setContentsMargins(0, 0, 0, 0)
                weather_layout.setSpacing(5)
                weather_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

                symbol = weather.code.to_character() if weather.code else None
                if symbol:
                    symbol_label = QtWidgets.QLabel(symbol)
                    font_family = getattr(self, "weather_font_family", "Weather Icons")
                    symbol_label.setFont(QtGui.QFont(font_family, 10))
                    weather_layout.addWidget(symbol_label)

                weather_label = QtWidgets.QLabel(f"{temp:.1f}°C")
                weather_label.setFont(QtGui.QFont("Arial", 10))
                weather_layout.addWidget(weather_label)

                info_layout.addWidget(weather_container)

        # 3. Playback
        playback_title = self.display_content.current_playback_title()
        if playback_title:
            if len(playback_title) > 12:
                playback_title = playback_title[:10] + "..."
            playback_label = QtWidgets.QLabel(f"♫ {playback_title}")
            playback_label.setFont(QtGui.QFont("Arial", 10))
            playback_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            info_layout.addWidget(playback_label)

        # 4. Volume
        if self.display_content.show_volume_meter:
            vol = self.display_content.current_volume()
            vol_label = QtWidgets.QLabel(f"Vol: {int(vol * 100)}%")
            vol_label.setFont(QtGui.QFont("Arial", 10, QtGui.QFont.Bold))
            vol_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            info_layout.addWidget(vol_label)

        layout.addLayout(info_layout, stretch=1)

    def draw_widget(self) -> Image.Image:
        if not QtWidgets.QApplication.instance():
            self.app = QtWidgets.QApplication([])
            
            # Load Weather Font
            id = QtGui.QFontDatabase.addApplicationFont(PresentationFont.weather_font)
            if id != -1:
                families = QtGui.QFontDatabase.applicationFontFamilies(id)
                if families:
                    self.weather_font_family = families[0]

            # Load Nerd Font
            id_nerd = QtGui.QFontDatabase.addApplicationFont(PresentationFont.default_font)
            if id_nerd != -1:
                families = QtGui.QFontDatabase.applicationFontFamilies(id_nerd)
                if families:
                    self.nerd_font_family = families[0]

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
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)

        if self.display_content.room_brightness.is_highly_dimmed():
            self._draw_dimmed_content(layout)
        else:
            self._draw_normal_content(layout)

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
        # self.current_display_image = self.present_my()
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

    def present(self) -> Image.Image:
        self.composable_presenters.refresh()
        return self.composable_presenters()


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
