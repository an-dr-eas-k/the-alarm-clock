from PIL import ImageDraw, Image
from PIL.ImageFont import FreeTypeFont
from luma.core.image_composition import ComposableImage

import logging

logger = logging.getLogger("utils.drawing")


def get_concat_h(im1, im2, bg_color=(0, 0, 0, 0)):
    height = max(im1.height, im2.height)
    dst = Image.new("RGBA", (im1.width + im2.width, height), bg_color)
    y = int((height - im1.height) / 2)
    dst.paste(im1, (0, y))
    y = int((height - im2.height) / 2)
    dst.paste(im2, (im1.width, y))
    return dst


def get_concat_v(im1, im2, bg_color=(0, 0, 0, 0)):
    width = max(im1.width, im2.width)
    dst = Image.new("RGBA", (width, im1.height + im2.height), bg_color)
    x = int((width - im1.width) / 2)
    dst.paste(im1, (x, 0))
    x = int((width - im2.width) / 2)
    dst.paste(im2, (x, im1.height))
    return dst


def get_concat_h_multi_blank(im_list, bg_color=(0, 0, 0, 0)):
    _im = im_list.pop(0)
    for im in im_list:
        _im = get_concat_h(_im, im, bg_color=bg_color)
    return _im


def text_to_image(
    text: str,
    font: FreeTypeFont,
    fg_color,
    bg_color="black",
    mode: str = "RGB",
) -> Image.Image:
    box = font.getbbox(text)
    img = Image.new(mode, (box[2] - box[0], box[3] - box[1]), bg_color)
    ImageDraw.Draw(img).text([-box[0], -box[1]], text, font=font, fill=fg_color)
    return img


def grayscale_to_color(grayscale_value: int):
    return (grayscale_value << 16) | (grayscale_value << 8) | grayscale_value


class ComposableImage(object):
    empty_image = Image.new("RGBA", (0, 0))
    _bounding_box = (None, None, None, None)

    def __init__(self, position: callable = None):
        self._position: callable = position if position else lambda _, _1: (0, 0)

    def position(self, width, height) -> tuple[int, int]:
        self._bounding_box = self._position(width, height) + (
            self._bounding_box[2],
            self._bounding_box[3],
        )
        return (self._bounding_box[0], self._bounding_box[1])

    def set_dimensions(self, width, height):
        self._bounding_box = self._bounding_box[:2] + (width, height)

    def is_present(self) -> bool:
        return False

    def draw(self) -> Image.Image:
        raise ValueError("no image available")

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        return self._bounding_box


class ImageComposition(object):
    debug: bool = False

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
        self._clear_screen()
        for comp_img in self.composed_images:
            comp_img: ComposableImage = comp_img
            if comp_img.is_present():
                self.draw(comp_img)
        self._background_image.crop(box=self._bounding_box)

    def draw(self, comp_img: ComposableImage):
        pil_img = comp_img.draw()
        comp_img.set_dimensions(pil_img.width, pil_img.height)
        logger.debug(
            f"refresh ({comp_img.__class__.__name__}): {pil_img.width}x{pil_img.height}"
        )
        if self.debug and pil_img.width > 0 and pil_img.height > 0:
            draw = ImageDraw.Draw(pil_img)
            x0, y0, x1, y1 = 0, 0, pil_img.width - 1, pil_img.height - 1
            draw.rectangle((x0, y0, x1, y1), outline=grayscale_to_color(6 * 16))
            del draw
        self._background_image.paste(
            pil_img, comp_img.position(pil_img.width, pil_img.height)
        )

    def clear(self):
        self.composed_images.clear()

    def _clear_screen(self):
        draw = ImageDraw.Draw(self._background_image)
        draw.rectangle(self._bounding_box, fill="black")
        del draw


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
        self.must_scroll = False
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
                self.rewind()

        elif self.state == self.SCROLLING:
            if self.image_x_pos < self.max_pos:
                if self.must_scroll:
                    self.image_x_pos += self.speed
            else:
                self.state = self.WAIT_REWIND

        return rendered_image

    def rewind(self):
        if self.must_scroll:
            self.image_x_pos = 0
        self.state = self.WAIT_SCROLL

    def is_scrolling(self) -> bool:
        return self.must_scroll

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
