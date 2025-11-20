from typing import Optional
from enum import Enum
import logging
from PIL import ImageFont, Image, ImageOps

from core.domain.mode_coordinator import AlarmEditingService, ModeName
from core.domain.model import AlarmDefinition
from core.interface.display.display_content import DisplayContent
from utils.drawing import (
    PresentationFont,
    text_to_image,
    ComposableImage,
    Scroller,
)


from core.interface.display.format import DisplayFormatter
from utils.extensions import T

logger = logging.getLogger("tac.display")


class Presenter(ComposableImage):
    font_file_7segment = PresentationFont.bold_clock_font
    font_file_nerd = PresentationFont.default_font

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

    def current_mode(self) -> Optional[ModeName]:
        """Get the current mode from the mode coordinator."""
        coordinator = self.content.alarm_clock_context.mode_coordinator
        return coordinator.current_mode_name if coordinator else None

    def editing_service(self) -> Optional[AlarmEditingService]:
        """Get the editing service if in an editing mode."""
        coordinator = self.content.alarm_clock_context.mode_coordinator
        return coordinator.editing_service if coordinator else None


class DefaultPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self) -> bool:
        return self.current_mode() == ModeName.DEFAULT


class AlarmEditorPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def get_alarm_definition(self) -> AlarmDefinition:
        service = self.editing_service()
        if service is not None and service.alarm_definition_in_editing is not None:
            return service.alarm_definition_in_editing
        return None

    def is_present(self) -> bool:
        mode = self.current_mode()
        return mode in (
            ModeName.ALARM_VIEW,
            ModeName.ALARM_EDIT,
            ModeName.PROPERTY_EDIT,
        )


class SimpleTextPresenter(AlarmEditorPresenter):
    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        position,
        text: callable,
        edit_mode: str,
    ) -> None:
        super().__init__(formatter, content, position)
        self.text = text
        self.edit_mode = edit_mode

    def draw(self) -> Image.Image:
        service = self.editing_service()
        font = self.formatter.default_font(size=20)
        effect_image = text_to_image(
            self.text(self.get_alarm_definition()),
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
        if service is None or not service.is_in_edit_mode([self.edit_mode]):
            return effect_image

        return ImageOps.expand(effect_image, border=1, fill="white")


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
        return self.content.alarm_clock_context.config.debug_level >= 5

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
