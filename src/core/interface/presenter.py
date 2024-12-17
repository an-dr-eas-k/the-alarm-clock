from typing import TypeVar, Optional, Type, cast
from enum import Enum
import logging
from luma.core.device import device as luma_device
from PIL import ImageFont, Image

from core.domain import (
    AlarmDefinition,
    AlarmEditorMode,
    AlarmViewMode,
    DefaultMode,
    DisplayContent,
    TACEventSubscriber,
)
from utils.drawing import (
    text_to_image,
    ComposableImage,
    Scroller,
)

from resources.resources import fonts_dir

from core.interface.format import DisplayFormatter
from utils.extensions import T

logger = logging.getLogger("tac.display")


class ColorType(Enum):
    IN16 = 0
    IN256 = 1
    INCOLOR = 2


class Presenter(TACEventSubscriber, ComposableImage):
    font_file_7segment = f"{fonts_dir}/DSEG7Classic-Regular.ttf"
    font_file_nerd = f"{fonts_dir}/CousineNerdFontMono-Regular.ttf"

    content: DisplayContent

    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        position: callable = None,
    ) -> None:
        super().__init__(position)
        self.formatter = formatter
        self.content = content

    def machine_state(self, expected_type: Type[T] = None) -> Optional[T]:
        state = self.content.state.state_machine.current_state
        if expected_type is None:
            return state
        if isinstance(state, expected_type):
            return cast(T, state)
        return None


class DefaultPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self) -> bool:
        return isinstance(self.machine_state(), DefaultMode)


class AlarmEditorPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def get_alarm_definition(self) -> AlarmDefinition:
        if isinstance(self.machine_state(), AlarmViewMode):
            return self.content.state.config.alarm_definitions[
                self.machine_state().alarm_index
            ]
        else:
            return None

    def is_present(self) -> bool:
        return isinstance(self.machine_state(), AlarmViewMode)


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
        content: DisplayContent,
        size: tuple[int, int],
    ) -> None:
        super().__init__(formatter, content)
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
            anchor="mm",
        )
