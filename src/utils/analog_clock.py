import math
from PIL import Image, ImageDraw
from datetime import datetime


class AnalogClockGenerator:
    def __init__(
        self,
        hour_hand_color: tuple = (255, 255, 255, 255),
        minute_hand_color: tuple = (255, 255, 255, 255),
        second_hand_color: tuple = (255, 255, 255, 255),
        origin_color: tuple = (255, 255, 255, 255),
        hour_markings_color: tuple = (255, 255, 255, 255),
        background_color: tuple = (0, 0, 0, 0),
        hour_markings_width: int = 5,
        hour_markings_length: int = 20,
        hour_hand_width: int = 7,
        minute_hand_width: int = 5,
        second_hand_width: int = 3,
    ):

        self.hour_hand_color = hour_hand_color
        self.minute_hand_color = minute_hand_color
        self.second_hand_color = second_hand_color
        self.origin_color = origin_color
        self.hour_markings_color = hour_markings_color
        self.background_color = background_color

        self.hour_markings_width = hour_markings_width
        self.hour_markings_length = hour_markings_length
        self.hour_hand_width = hour_hand_width
        self.minute_hand_width = minute_hand_width
        self.second_hand_width = second_hand_width

    def get_current_clock(
        self, now: datetime = datetime.now(), clock_radius: int = 31
    ) -> Image.Image:

        hour = now.hour
        minute = now.minute
        second = now.second

        return self.get_clock(hour, minute, second, clock_radius)

    def get_clock(
        self, hour: int, minute: int, second: int, clock_radius: int = 31
    ) -> Image.Image:

        canvas = Image.new(
            "RGBA",
            (clock_radius * 2 + 1, clock_radius * 2 + 1),
            color=self.background_color,
        )
        draw = ImageDraw.Draw(canvas)

        center = clock_radius

        # Draw hour markings
        self.draw_hour_markings(
            draw,
            center,
            start_distance=clock_radius - self.hour_markings_length,
            length=self.hour_markings_length,
            width=self.hour_markings_width,
            color=self.hour_markings_color,
        )

        # Draw origin in the center
        radius = int(clock_radius / 7)
        draw.ellipse(
            (center - radius, center - radius, center + radius, center + radius),
            fill=self.origin_color,
        )

        # Draw hour hand
        length = int(clock_radius / 7 * 4)
        angle = hour * (360 / 12) + minute * (360 / 12) / 60
        self.draw_hand(
            draw, center, angle, length, self.hour_hand_color, self.hour_hand_width
        )

        # Draw minute hand
        length = int(clock_radius * 0.90)
        angle = minute * (360 / 60) + second * (360 / 60) / 60
        self.draw_hand(
            draw, center, angle, length, self.minute_hand_color, self.minute_hand_width
        )

        # Draw second hand
        length = int(clock_radius)
        angle = second * (360 / 60)
        self.draw_hand(
            draw, center, angle, length, self.second_hand_color, self.second_hand_width
        )

        return canvas

    # -------------- #
    # Helper methods #
    # -------------- #

    def draw_hand(
        self,
        draw: ImageDraw.ImageDraw,
        center,
        angle,
        length,
        color: tuple = (255, 255, 255, 255),
        width: int = 1,
    ):
        if width <= 0:
            return
        x_end = center + length * math.sin(math.radians(angle))
        y_end = center - length * math.cos(math.radians(angle))
        draw.line((center, center, x_end, y_end), fill=color, width=width)

    def draw_hour_markings(
        self,
        draw: ImageDraw.ImageDraw,
        center,
        start_distance: int = 170,
        length: int = 50,
        color: tuple = (255, 255, 255, 255),
        width: int = 5,
    ):

        if length < 0 or width < 0:
            return

        for i in range(0, 12):
            angle = i * (360 / 12)
            x_start = center + start_distance * math.sin(math.radians(angle))
            y_start = center + start_distance * math.cos(math.radians(angle))

            x_end = center + (start_distance + length) * math.sin(math.radians(angle))
            y_end = center + (start_distance + length) * math.cos(math.radians(angle))
            draw.line((x_start, y_start, x_end, y_end), fill=color, width=width)
