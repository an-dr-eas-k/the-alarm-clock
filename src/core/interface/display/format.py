import datetime
from enum import Enum
import logging
from PIL import Image
from PyQt5 import QtGui
from core.domain.mode_coordinator import ModeName
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

    def clock_font(self, size: int = 20, weight: int = QtGui.QFont.Weight.Bold):
        font_path = (
            PresentationFont.roboto_font
            if not self.be_gloomy()
            else PresentationFont.light_clock_font
        )
        return PresentationFont.get_font_family(font_path, size, weight)

    def info_font(self, size: int = 18, weight: int = QtGui.QFont.Weight.Normal):
        font_path = (
            PresentationFont.roboto_font
            if not self.be_gloomy()
            else PresentationFont.light_clock_font
        )
        return PresentationFont.get_font_family(font_path, size, weight)

    def weather_font(self, size: int = 18, weight: int = QtGui.QFont.Weight.Normal):
        return PresentationFont.get_font_family(
            PresentationFont.weather_font, size, weight
        )

    def be_gloomy(self):
        is_visual_effect_active = (
            True
            and self.display_content.next_alarm_info is not None
            and self.display_content.next_alarm_info.visual_effect is not None
            and self.display_content.next_alarm_info.visual_effect.is_active()
        )
        is_in_setting_menu = (
            True
            and self.alarm_clock_context.mode_coordinator is not None
            and self.alarm_clock_context.mode_coordinator.current_mode_name
            != ModeName.DEFAULT
        )
        return (
            True
            and self.display_content.room_brightness.is_highly_dimmed()
            and not self.display_content.show_volume_meter
            and self.display_content.playback_content.playback_mode == Mode.Idle
            and not is_visual_effect_active
            and not is_in_setting_menu
        )

    def update_formatter(self):
        self.adjust_display()
        logger.debug(
            "room_brightness: %s, time_delta_to_alarm: %smin, display_formatter: %s",
            self.display_content.room_brightness,
            "{:.2f}".format(self.display_content.next_alarm_info.minutes_until_alarm()),
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
        self.adjust_display_by_alarm()
        if not self.be_gloomy():
            self._foreground_grayscale_16 = max(3, self._foreground_grayscale_16)

    def adjust_display_by_room_brightness(self):
        self._background_grayscale_16 = 0
        self._foreground_grayscale_16 = (
            self.display_content.room_brightness.get_grayscale_value(min_value=1)
        )

    def adjust_display_by_alarm(self):
        next_alarm_info = self.display_content.next_alarm_info

        visual_effect = (
            next_alarm_info.visual_effect
            if self.display_content.has_next_alarm()
            else None
        )

        self.adjust_display_by_alarm_visual_effect(visual_effect)

    def adjust_display_by_alarm_visual_effect(self, visual_effect: VisualEffect):

        if not visual_effect or not visual_effect.is_active():
            if self._visual_effect_active:
                self._visual_effect_active = False
            return

        self._visual_effect_active = True

        style = visual_effect.get_style()
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

            # Use a lookup table for faster processing
            lut = [fg_color] * 256
            if 0 <= bg_color < 256:
                lut[bg_color] = bg_color

            if im.mode == "RGB":
                lut = lut * 3

            im = im.point(lut)
        return im
