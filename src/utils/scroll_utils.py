from PIL import Image, ImageDraw
from luma.core.render import canvas
from luma.core.image_composition import ComposableImage

import logging

logger = logging.getLogger("tac.scroll_utils")


class ComposableImage(object):
    empty_image = Image.new("RGBA", (0, 0))
    debug: bool = False

    def __init__(self, position: callable = None):
        self._position: callable = position if position else lambda _, _1: (0, 0)

    def position(self, width, height) -> tuple[int, int]:
        return self._position(width, height)

    def is_present(self) -> bool:
        return False

    def draw(self) -> Image.Image:
        raise ValueError("no image available")

    def draw_if_present(self) -> Image.Image:
        if not self.is_present():
            return self.empty_image
        image = self.draw()
        logger.debug(
            f"draw_if_present ({self.__class__.__name__}): {image.width}x{image.height}"
        )
        if self.debug and image.width > 0 and image.height > 0:
            draw = ImageDraw.Draw(image)
            x0, y0, x1, y1 = 0, 0, image.width - 1, image.height - 1
            draw.rectangle((x0, y0, x1, y1), outline="white")
            del draw
        return image


class ImageComposition(object):

    def __init__(self, background_image: Image):
        self._background_image: Image.Image = background_image
        self._bounding_box = (
            0,
            0,
            self._background_image.width - 1,
            self._background_image.height - 1,
        )
        self.composed_images = []

    def add_image(self, image: ComposableImage):
        assert image
        self.composed_images.append(image)

    def remove_image(self, image: ComposableImage):
        assert image
        self.composed_images.remove(image)

    def __call__(self):
        return self._background_image

    def refresh(self):
        self._clear()
        for img in self.composed_images:
            img: ComposableImage = img
            pil_img = img.draw_if_present()
            self._background_image.paste(
                pil_img, img.position(pil_img.width, pil_img.height)
            )
        self._background_image.crop(box=self._bounding_box)

    def _clear(self):
        draw = ImageDraw.Draw(self._background_image)
        draw.rectangle(self._bounding_box, fill="black")
        del draw


class TextImage:
    def __init__(self, device, text, font):
        with canvas(device) as draw:
            left, top, right, bottom = draw.textbbox((0, 0), text, font)
            w, h = right - left, bottom - top

        self.image = Image.new(device.mode, (w, h))
        draw = ImageDraw.Draw(self.image)
        draw.text((0, 0), text, font=font, fill="white")
        del draw
        self.width = w
        self.height = h


class Synchroniser:
    def __init__(self):
        self.synchronised = {}

    def busy(self, task):
        self.synchronised[id(task)] = False

    def ready(self, task):
        self.synchronised[id(task)] = True

    def is_synchronised(self):
        for task in self.synchronised.items():
            if task[1] is False:
                return False
        return True


class Scroller:
    WAIT_SCROLL = 1
    SCROLLING = 2
    WAIT_REWIND = 3
    WAIT_SYNC = 4

    def __init__(
        self,
        canvas_width: int,
        scroll_delay,
        scroll_speed: int = 2,
        synchroniser: Synchroniser = None,
    ):
        if synchroniser is None:
            synchroniser = Synchroniser()
        self.canvas_width = canvas_width
        self.speed = scroll_speed
        self.delay = scroll_delay
        self.synchroniser = synchroniser
        self.image_x_pos = 0
        self.ticks = 0
        self.state = self.WAIT_SCROLL
        self.synchroniser.busy(self)

    def tick(self, rendered_image):
        self.max_pos = rendered_image.width - self.canvas_width
        self.must_scroll = self.max_pos > 0
        rendered_image = self.render(rendered_image)

        # Repeats the following sequence:
        #  wait - scroll - wait - rewind -> sync with other scrollers -> wait
        if self.state == self.WAIT_SCROLL:
            if not self.is_waiting():
                self.state = self.SCROLLING
                self.synchroniser.busy(self)

        elif self.state == self.WAIT_REWIND:
            if not self.is_waiting():
                self.synchroniser.ready(self)
                self.state = self.WAIT_SYNC

        elif self.state == self.WAIT_SYNC:
            if self.synchroniser.is_synchronised():
                if self.must_scroll:
                    self.image_x_pos = 0
                self.state = self.WAIT_SCROLL

        elif self.state == self.SCROLLING:
            if self.image_x_pos < self.max_pos:
                if self.must_scroll:
                    self.image_x_pos += self.speed
            else:
                self.state = self.WAIT_REWIND

        return rendered_image

    def render(self, rendered_image: Image.Image):
        return rendered_image.crop(
            (
                self.image_x_pos,
                0,
                self.image_x_pos + self.canvas_width,
                rendered_image.height,
            )
        )

    def is_waiting(self):
        self.ticks += 1
        if self.ticks > self.delay:
            self.ticks = 0
            return False
        return True
