import datetime
from enum import Enum
import logging
from PIL import Image
from core.domain.mode_coordinator import DefaultMode
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    DisplayContent,
    VisualEffect,
)
from utils.drawing import PresentationFont, grayscale_to_color
from utils.extensions import get_job_arg, get_timedelta_to_alarm, respect_ranges

logger = logging.getLogger("tac.display")


class ColorType(Enum):
    IN16 = 0
    IN256 = 1
    INCOLOR = 2


class DisplayFormatter:

    _foreground_grayscale_16: int
    _background_grayscale_16: int

    _visual_effect_active: bool = False
    _clear_display: bool = False

    def __init__(self, content: DisplayContent, alarm_clock_context: AlarmClockContext):
        self.display_content = content
        self.alarm_clock_context = alarm_clock_context

    def clock_font(self, size: int = 50):
        if self.highly_dimmed():
            return PresentationFont.get_font(PresentationFont.light_clock_font, 20)
        return PresentationFont.get_font(PresentationFont.bold_clock_font, size)

    def default_font(self, size: int = 18):
        return PresentationFont.get_font(PresentationFont.default_font, size)

    def clear_display(self):
        clear_display = self._clear_display
        self._clear_display = False
        return clear_display

    def highly_dimmed(self):
        return self.alarm_clock_context.room_brightness.is_highly_dimmed()

    def update_formatter(self):
        self.adjust_display()
        logger.debug(
            "room_brightness: %s, time_delta_to_alarm: %sh, display_formatter: %s",
            self.alarm_clock_context.room_brightness(),
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

    def adjust_display_by_room_brightness(self):
        self._background_grayscale_16 = 0
        self._foreground_grayscale_16 = (
            self.alarm_clock_context.room_brightness.get_grayscale_value(min_value=1)
        )

    def adjust_display_by_mode(self):
        current_state = (
            self.alarm_clock_context.state_machine.current_state
            if self.alarm_clock_context.state_machine
            else None
        )

        if current_state is None:
            return

        if not isinstance(current_state, DefaultMode):
            self._background_grayscale_16 = 0
            self._foreground_grayscale_16 = 15

    def adjust_display_by_alarm(self):
        next_alarm_job = (
            self.display_content.next_alarm_job
            if self.display_content or self.display_content.next_alarm_job
            else None
        )
        visual_effect: VisualEffect = (
            get_job_arg(next_alarm_job, AlarmDefinition).visual_effect
            if next_alarm_job is not None
            else None
        )

        self.adjust_display_by_alarm_visual_effect(
            get_timedelta_to_alarm(next_alarm_job), visual_effect
        )

    def adjust_display_by_alarm_visual_effect(
        self, time_delta_to_alarm: datetime.timedelta, visual_effect: VisualEffect
    ):

        alarm_in_minutes = time_delta_to_alarm.total_seconds() / 60

        if not visual_effect or not visual_effect.is_active(alarm_in_minutes):
            if self._visual_effect_active:
                self._clear_display = True
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
        return self.format_dseg7_string(clock_string, desired_length=5)

    def format_dseg7_string(self, dseg7: str, desired_length: int = None) -> str:
        if desired_length is None:
            desired_length = len(dseg7)

        dseg7 = dseg7.lower().replace("7", "`").replace("s", "5").replace("i", "1")
        dseg7 = "!" * (desired_length - len(dseg7)) + dseg7
        return dseg7

    def postprocess_image(self, im: Image.Image) -> Image.Image:
        if self.highly_dimmed():
            fg_color = self.foreground_color(color_type=ColorType.IN256)
            bg_color = self.background_color(color_type=ColorType.IN256)

            def replace_colors(pixel):
                if pixel == bg_color:
                    return bg_color
                return fg_color

            im = im.point(replace_colors)

        return im
