import datetime
from enum import Enum
import logging
from PIL import Image
from PyQt5 import QtGui
from core.domain.model import (
    AlarmClockContext,
    Mode,
    VisualEffect,
)
from core.interface.display.display_content import DisplayContent
from utils.drawing import PresentationFont, grayscale_to_color
from utils.extensions import respect_ranges

logger = logging.getLogger("tac.core.interface.display.format")


class ColorType(Enum):
    IN16 = 0
    IN256 = 1
    INCOLOR = 2
    INHEX = 3


class DisplayFormatter:

    _foreground_grayscale_16: int
    _background_grayscale_16: int

    _visual_effect_active: bool = False

    def __init__(self, content: DisplayContent, alarm_clock_context: AlarmClockContext):
        self.display_content = content
        self.alarm_clock_context = alarm_clock_context

    def clock_font_pil(self, size: int = 50):
        if self.be_gloomy():
            return PresentationFont.get_font(PresentationFont.light_clock_font, 20)
        return PresentationFont.get_font(PresentationFont.bold_clock_font, size)

    def clock_font(self, size: int = 20, weight: int = QtGui.QFont.Weight.Bold):
        font_family = PresentationFont.get_font_family(
            PresentationFont.roboto_font
            if not self.be_gloomy()
            else PresentationFont.light_clock_font
        )
        return QtGui.QFont(font_family, size, weight)

    def info_font_pil(self, size: int = 18):
        return PresentationFont.get_font(PresentationFont.info_font, size)

    def info_font(self, size: int = 18, weight: int = QtGui.QFont.Weight.Normal):
        font_family = PresentationFont.get_font_family(PresentationFont.roboto_font)
        return QtGui.QFont(font_family, size, weight)

    def weather_font_pil(self, size: int = 18):
        return PresentationFont.get_font(PresentationFont.weather_font, size)

    def weather_font(self, size: int = 18):
        font_family = PresentationFont.get_font_family(PresentationFont.weather_font)
        return QtGui.QFont(font_family, size, QtGui.QFont.Weight.Normal)

    def be_gloomy(self):
        return (
            True
            and self.display_content.room_brightness.is_highly_dimmed()
            and self.display_content.playback_content.playback_mode == Mode.Idle
        )

    def update_formatter(self):
        self.adjust_display()
        logger.debug(
            "room_brightness: %s, time_delta_to_alarm: %sh, display_formatter: %s",
            self.display_content.room_brightness,
            "{:.2f}".format(
                self.display_content.get_timedelta_to_alarm().total_seconds() / 3600
            ),
            self.__dict__,
        )

    def _color(
        self,
        color: int,
        min_value=0,
        max_value=15,
        color_type: ColorType = ColorType.INCOLOR,
    ):
        grayscale_16 = respect_ranges(color, min_value, max_value)

        if color_type == ColorType.IN16:
            return grayscale_16
        if color_type == ColorType.IN256:
            return grayscale_16 * 16
        if color_type == ColorType.INCOLOR:
            return grayscale_to_color(grayscale_16 * 16)
        if color_type == ColorType.INHEX:
            level = int(grayscale_16)
            level = max(0, min(15, level))
            gray = int(round(level / 15 * 255))
            return f"#{gray:02x}{gray:02x}{gray:02x}"

    def foreground_color(
        self, min_value: int = 1, color_type: ColorType = ColorType.INCOLOR
    ):
        return self._color(
            self._foreground_grayscale_16, min_value, color_type=color_type
        )

    def background_color(self, color_type: ColorType = ColorType.INCOLOR):
        return self._color(self._background_grayscale_16, color_type=color_type)

    def adjust_display(self):
        self.adjust_display_by_room_brightness()
        self.adjust_display_by_mode()
        self.adjust_display_by_alarm()
        if not self.be_gloomy():
            self._foreground_grayscale_16 = max(3, self._foreground_grayscale_16)

    def adjust_display_by_room_brightness(self):
        self._background_grayscale_16 = 0
        self._foreground_grayscale_16 = (
            self.display_content.room_brightness.get_grayscale_value(min_value=1)
        )

    def adjust_display_by_mode(self):
        from core.domain.mode_coordinator import ModeName

        current_mode = (
            self.alarm_clock_context.mode_coordinator.current_mode_name
            if self.alarm_clock_context.mode_coordinator
            else None
        )

        if current_mode is None:
            return

        if current_mode != ModeName.DEFAULT:
            self._background_grayscale_16 = 0
            self._foreground_grayscale_16 = 15

    def adjust_display_by_alarm(self):
        next_alarm_info = self.display_content.next_alarm_info

        visual_effect = (
            next_alarm_info.visual_effect if next_alarm_info.has_alarm() else None
        )

        self.adjust_display_by_alarm_visual_effect(
            next_alarm_info.get_timedelta_to_alarm(), visual_effect
        )

    def adjust_display_by_alarm_visual_effect(
        self, time_delta_to_alarm: datetime.timedelta, visual_effect: VisualEffect
    ):

        alarm_in_minutes = time_delta_to_alarm.total_seconds() / 60

        if not visual_effect or not visual_effect.is_active(alarm_in_minutes):
            if self._visual_effect_active:
                self._visual_effect_active = False
            return

        logger.debug("visual effect active: %s", alarm_in_minutes)
        self._visual_effect_active = True

        style = visual_effect.get_style(alarm_in_minutes)
        self._background_grayscale_16 = style.background_grayscale_16
        self._foreground_grayscale_16 = style.foreground_grayscale_16

    def format_clock_string(
        self, clock: datetime, show_blink_segment: bool = True
    ) -> str:
        blink_segment = (
            self.alarm_clock_context.config.blink_segment if show_blink_segment else " "
        )
        clock_string = clock.strftime(
            self.alarm_clock_context.config.clock_format_string.replace(
                "<blinkSegment>", blink_segment
            )
        )
        return clock_string

    def format_dseg7_clock_string(
        self,
        clock: datetime,
        show_blink_segment: bool = True,
        desired_length: int = 5,
    ) -> str:
        dseg7 = self.format_clock_string(clock, show_blink_segment)
        return self.format_dseg7_string(dseg7, desired_length=desired_length)

    def format_dseg7_string(
        self,
        dseg7: str,
        desired_length: int = None,
    ) -> str:
        if desired_length is None:
            desired_length = len(dseg7)

        dseg7 = dseg7.lower().replace("7", "`").replace("s", "5").replace("i", "1")
        dseg7 = "!" * (desired_length - len(dseg7)) + dseg7
        return dseg7

    def postprocess_image(self, im: Image.Image) -> Image.Image:
        if self.be_gloomy():
            fg_color = self.foreground_color(color_type=ColorType.IN256)
            bg_color = self.background_color(color_type=ColorType.IN256)

            def replace_colors(pixel):
                if pixel == bg_color:
                    return bg_color
                return fg_color

            im = im.point(replace_colors)

        return im
