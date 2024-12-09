import datetime
from enum import Enum
import logging
from luma.core.device import device as luma_device
from PIL import ImageFont, Image

from core.domain import (
    AlarmClockState,
    AlarmDefinition,
    DisplayContent,
    TACEventSubscriber,
    VisualEffect,
)
from utils.drawing import (
    grayscale_to_color,
    text_to_image,
    ComposableImage,
    Scroller,
)
from utils.extensions import get_job_arg, get_timedelta_to_alarm, respect_ranges

from resources.resources import fonts_dir

logger = logging.getLogger("tac.display")


class ColorType(Enum):
    IN16 = 0
    IN256 = 1
    INCOLOR = 2


class DisplayFormatter:
    _bold_clock_font = ImageFont.truetype(f"{fonts_dir}/DSEG7Classic-Regular.ttf", 50)
    _light_clock_font = ImageFont.truetype(
        f"{fonts_dir}/DSEG7ClassicMini-Light.ttf", 20
    )

    _foreground_grayscale_16: int
    _background_grayscale_16: int
    _clock_font: ImageFont

    _visual_effect_active: bool = False
    _clear_display: bool = False

    def __init__(self, content: DisplayContent, state: AlarmClockState):
        self.display_content = content
        self.state = state

    def clock_font(self):
        return self._clock_font

    def clear_display(self):
        clear_display = self._clear_display
        self._clear_display = False
        return clear_display

    def highly_dimmed(self):
        return self.state.room_brightness.is_highly_dimmed()

    def update_formatter(self):
        self.adjust_display()
        logger.debug(
            "room_brightness: %s, time_delta_to_alarm: %sh, display_formatter: %s",
            self.state.room_brightness(),
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
        self.adjust_display_by_alarm()

    def adjust_display_by_room_brightness(self):
        self._background_grayscale_16 = 0
        self._foreground_grayscale_16 = self.state.room_brightness.get_grayscale_value(
            min_value=1
        )
        self._clock_font = (
            self._light_clock_font if self.highly_dimmed() else self._bold_clock_font
        )

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
        self._clock_font = (
            self._bold_clock_font if style.be_bold else self._light_clock_font
        )

    def format_clock_string(
        self, clock: datetime, show_blink_segment: bool = True
    ) -> str:
        blink_segment = self.state.config.blink_segment if show_blink_segment else " "
        clock_string = clock.strftime(
            self.state.config.clock_format_string.replace(
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


class Presenter(TACEventSubscriber, ComposableImage):
    font_file_7segment = f"{fonts_dir}/DSEG7Classic-Regular.ttf"
    font_file_nerd = f"{fonts_dir}/CousineNerdFontMono-Regular.ttf"

    content: DisplayContent

    def __init__(
        self,
        formatter: DisplayFormatter,
        position: callable = None,
    ) -> None:
        super().__init__(position)
        self.formatter = formatter


class DefaultPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, position)
        self.content = content


class AlarmEditorPresenter(Presenter):
    def __init__(self, formatter: DisplayFormatter, position) -> None:
        super().__init__(formatter, position)

    def is_present(self) -> bool:
        return True


class ScrollingPresenter(DefaultPresenter):
    _scroller: Scroller = None

    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        canvas_width: int,
        position,
    ) -> None:
        super().__init__(formatter, content, position)
        self.canvas_width = canvas_width
        self._scroller = Scroller(self.canvas_width, 0, 5)

    def rewind_scroller(self):
        self._scroller.rewind()

    def scroll(self, image: Image.Image) -> Image.Image:
        scrolling_image = self._scroller.tick(image)
        if self._scroller.is_scrolling():
            self.content.is_scrolling = True
        return scrolling_image


class BackgroundPresenter(Presenter):
    def __init__(
        self,
        formatter: DisplayFormatter,
        _: DisplayContent,
        size: tuple[int, int],
    ) -> None:
        super().__init__(formatter)
        self._size = size

    def is_present(self) -> bool:
        return True

    def draw(self):
        return Image.new("RGB", self._size, color=self.formatter.background_color())


class RefreshPresenter(DefaultPresenter):
    _symbols = "-\\|/"
    _prev_symbol_index = 0

    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self):
        return self.content.state.config.debug_level >= 5

    def draw(self) -> Image.Image:

        self._prev_symbol_index = (self._prev_symbol_index + 1) % len(self._symbols)
        font_size = 15

        font = ImageFont.truetype(self.font_file_nerd, font_size)

        return text_to_image(
            self._symbols[self._prev_symbol_index],
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
