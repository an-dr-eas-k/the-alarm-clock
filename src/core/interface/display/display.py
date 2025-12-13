import logging
from timeit import timeit
import traceback
import time
from abc import ABC, abstractmethod
from typing import List, Tuple

from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import Image, ImageDraw

from core.domain.events import (
    AlarmTriggeredEvent,
    ForcedDisplayUpdateEvent,
)
from core.domain.edit_mode import AlarmProperty, EditorAction
from core.domain.model import (
    AlarmClockContext,
    Config,
    DisplayContentProvider,
    PlaybackContent,
    SpotifyStream,
)
from core.domain.mode_coordinator import ModeName
from core.interface.display.display_content import DisplayContent
from core.infrastructure.event_bus import EventBus
from core.interface.display.format import ColorType, DisplayFormatter

from utils.geolocation import GeoLocation

from resources.resources import display_shot_file

logger = logging.getLogger("tac.core.interface.display.display")


# --- UI Framework ---


def darken_color(hex_color, factor=0.7):
    if not hex_color:
        return "white"
    if hex_color.startswith("#"):
        hex_color = hex_color[1:]
    if len(hex_color) != 6:
        return hex_color  # Fallback
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


class Widget(ABC):
    def __init__(self):
        self.rect = (0, 0, 0, 0)  # x, y, w, h
        self.stretch = 0
        self.align = "center"  # 'start', 'center', 'end' (cross axis)

    @abstractmethod
    def min_size(self, draw: ImageDraw.ImageDraw) -> Tuple[int, int]:
        return (0, 0)

    def set_geometry(self, x, y, w, h):
        self.rect = (x, y, w, h)

    @abstractmethod
    def render(self, image: Image.Image, draw: ImageDraw.ImageDraw):
        pass


class Spacer(Widget):
    def __init__(self, width=0, height=0):
        super().__init__()
        self._width = width
        self._height = height

    def min_size(self, draw):
        return (self._width, self._height)

    def render(self, image, draw):
        pass


class Label(Widget):
    def __init__(self, text, font, color="white", align="left"):
        super().__init__()
        self.text = text
        self.font = font
        self.color = color
        self.text_align = align  # 'left', 'center', 'right' (text within widget)

    def min_size(self, draw):
        if not self.text:
            return (0, 0)
        bbox = draw.textbbox((0, 0), self.text, font=self.font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    def render(self, image, draw):
        x, y, w, h = self.rect
        bbox = draw.textbbox((0, 0), self.text, font=self.font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        draw_x = x
        if self.text_align == "center":
            draw_x = x + (w - tw) // 2
        elif self.text_align == "right":
            draw_x = x + w - tw

        # Vertical center
        draw_y = y + (h - th) // 2 - bbox[1]
        draw_x -= bbox[0]

        draw.text((draw_x, draw_y), self.text, font=self.font, fill=self.color)


class Layout(Widget):
    def __init__(self):
        super().__init__()
        self.children: List[Widget] = []
        self.spacing = 0
        self.margins = (0, 0, 0, 0)  # left, top, right, bottom

    def add_widget(self, widget: Widget, stretch=0, align="center"):
        widget.stretch = stretch
        widget.align = align
        self.children.append(widget)

    def set_margins(self, left, top, right, bottom):
        self.margins = (left, top, right, bottom)


class HBox(Layout):
    def min_size(self, draw):
        w, h = 0, 0
        for child in self.children:
            cw, ch = child.min_size(draw)
            w += cw
            h = max(h, ch)
        w += self.spacing * max(0, len(self.children) - 1)
        w += self.margins[0] + self.margins[2]
        h += self.margins[1] + self.margins[3]
        return (w, h)

    def render(self, image, draw):
        x, y, w, h = self.rect
        content_w = w - self.margins[0] - self.margins[2]
        content_h = h - self.margins[1] - self.margins[3]
        start_x = x + self.margins[0]
        start_y = y + self.margins[1]

        child_sizes = [c.min_size(draw) for c in self.children]

        total_stretch = sum(c.stretch for c in self.children)
        used_width = sum(
            s[0] for i, s in enumerate(child_sizes) if self.children[i].stretch == 0
        )
        used_width += self.spacing * max(0, len(self.children) - 1)

        remaining_width = max(0, content_w - used_width)

        current_x = start_x
        for i, child in enumerate(self.children):
            cw, ch = child_sizes[i]

            if child.stretch > 0:
                if total_stretch > 0:
                    cw = int(remaining_width * (child.stretch / total_stretch))
                else:
                    cw = 0

            # Vertical alignment
            cy = start_y
            if child.align == "center":
                cy = start_y  # Layouts handle their own vertical alignment usually, but here we pass full height

            child.set_geometry(current_x, start_y, cw, content_h)
            child.render(image, draw)
            current_x += cw + self.spacing


class VBox(Layout):
    def min_size(self, draw):
        w, h = 0, 0
        for child in self.children:
            cw, ch = child.min_size(draw)
            h += ch
            w = max(w, cw)
        h += self.spacing * max(0, len(self.children) - 1)
        w += self.margins[0] + self.margins[2]
        h += self.margins[1] + self.margins[3]
        return (w, h)

    def render(self, image, draw):
        x, y, w, h = self.rect
        content_w = w - self.margins[0] - self.margins[2]
        content_h = h - self.margins[1] - self.margins[3]
        start_x = x + self.margins[0]
        start_y = y + self.margins[1]

        child_sizes = [c.min_size(draw) for c in self.children]

        total_stretch = sum(c.stretch for c in self.children)
        used_height = sum(
            s[1] for i, s in enumerate(child_sizes) if self.children[i].stretch == 0
        )
        used_height += self.spacing * max(0, len(self.children) - 1)

        remaining_height = max(0, content_h - used_height)

        current_y = start_y
        for i, child in enumerate(self.children):
            cw, ch = child_sizes[i]

            if child.stretch > 0:
                if total_stretch > 0:
                    ch = int(remaining_height * (child.stretch / total_stretch))
                else:
                    ch = 0

            child.set_geometry(start_x, current_y, content_w, ch)
            child.render(image, draw)
            current_y += ch + self.spacing


class ClockWidget(Widget):
    def __init__(self, hour_str, min_str, blink_char, show_blink, fg_color, font):
        super().__init__()
        self.hour_str = hour_str
        self.min_str = min_str
        self.blink_char = blink_char
        self.show_blink = show_blink
        self.fg_color = fg_color
        self.font = font
        self.gray_color = darken_color(fg_color)

    def min_size(self, draw):
        w = 0
        overlap = 12

        def measure_str(s):
            width = 0
            for i, char in enumerate(s):
                bbox = draw.textbbox((0, 0), char, font=self.font)
                cw = bbox[2] - bbox[0]
                if i < len(s) - 1:
                    width += cw - overlap
                else:
                    width += cw
            return width

        w += measure_str(self.hour_str)
        w -= 15

        bbox = draw.textbbox((0, 0), self.blink_char, font=self.font)
        w += bbox[2] - bbox[0]
        w -= 10

        w += measure_str(self.min_str)

        bbox_h = draw.textbbox((0, 0), "0", font=self.font)
        h = bbox_h[3] - bbox_h[1] + 10
        return (w, h)

    def render(self, image, draw):
        x, y, w, h = self.rect

        bbox_sample = draw.textbbox((0, 0), "0", font=self.font)
        font_h = bbox_sample[3] - bbox_sample[1]
        base_y = y + (h - font_h) // 2 - bbox_sample[1]

        overlap = 12
        vertical_shift = 2

        current_x = x

        # Draw Hours
        for i, char in enumerate(self.hour_str):
            color = self.fg_color if i == 0 else self.gray_color
            offset_y = -vertical_shift if i == 0 else vertical_shift

            draw.text((current_x, base_y + offset_y), char, font=self.font, fill=color)

            bbox = draw.textbbox((0, 0), char, font=self.font)
            cw = bbox[2] - bbox[0]

            if i < len(self.hour_str) - 1:
                current_x += cw - overlap
            else:
                current_x += cw

        current_x -= 15

        # Separator
        if self.show_blink:
            draw.text(
                (current_x, base_y), self.blink_char, font=self.font, fill=self.fg_color
            )

        bbox = draw.textbbox((0, 0), self.blink_char, font=self.font)
        current_x += bbox[2] - bbox[0]
        current_x -= 10

        # Draw Minutes
        for i, char in enumerate(self.min_str):
            color = self.fg_color if i == 0 else self.gray_color
            offset_y = -vertical_shift if i == 0 else vertical_shift

            draw.text((current_x, base_y + offset_y), char, font=self.font, fill=color)

            bbox = draw.textbbox((0, 0), char, font=self.font)
            cw = bbox[2] - bbox[0]

            if i < len(self.min_str) - 1:
                current_x += cw - overlap
            else:
                current_x += cw


class ScrollingLabel(Widget):
    def __init__(self, text, font, color, start_time, display_content, speed=30):
        super().__init__()
        self.text = text
        self.font = font
        self.color = color
        self.start_time = start_time
        self.display_content = display_content
        self.speed = speed

    def min_size(self, draw):
        bbox = draw.textbbox((0, 0), "A", font=self.font)
        return (10, bbox[3] - bbox[1])

    def render(self, image, draw):
        x, y, w, h = self.rect
        bbox = draw.textbbox((0, 0), self.text, font=self.font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        draw_y = y + (h - text_height) // 2 - bbox[1]

        if text_width <= w:
            draw.text((x - bbox[0], draw_y), self.text, font=self.font, fill=self.color)
        else:
            self.display_content.is_scrolling = True
            elapsed = time.time() - self.start_time
            pause_duration = 2.0

            if elapsed < pause_duration:
                offset = 0
            else:
                offset = (elapsed - pause_duration) * self.speed

            gap = 30
            total_cycle_width = text_width + gap
            current_offset = offset % total_cycle_width

            # Create a temporary image for clipping
            temp_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            temp_draw = ImageDraw.Draw(temp_img)

            x1 = -current_offset
            if x1 + text_width > 0:
                temp_draw.text(
                    (x1 - bbox[0], (h - text_height) // 2 - bbox[1]),
                    self.text,
                    font=self.font,
                    fill=self.color,
                )

            x2 = x1 + total_cycle_width
            if x2 < w:
                temp_draw.text(
                    (x2 - bbox[0], (h - text_height) // 2 - bbox[1]),
                    self.text,
                    font=self.font,
                    fill=self.color,
                )

            image.paste(temp_img, (x, y), temp_img)


class Display(DisplayContentProvider):

    device: luma_device
    display_content: DisplayContent

    _last_playback_title: str = None
    _playback_title_scroll_start_time: float = 0

    def __init__(
        self,
        device: luma_device,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        display_formatter: DisplayFormatter,
        alarm_clock_context: AlarmClockContext,
        event_bus: EventBus = None,
    ) -> None:
        self.device = device
        logger.info("device mode: %s", self.device.mode)
        self.display_content = display_content
        self.playback_content = playback_content
        self.alarm_clock_context = alarm_clock_context
        self.event_bus = event_bus
        self.formatter = display_formatter
        # self.initialize_qt_app() # Removed
        self.event_bus.on(ForcedDisplayUpdateEvent)(
            self._handle_forced_display_update_event
        )
        self.event_bus.on(AlarmTriggeredEvent)(self._alarm_triggered)

    def _alarm_triggered(self, _: AlarmTriggeredEvent):
        self.device.hide()
        self.device.show()
        self.safe_refresh_display()

    def _handle_forced_display_update_event(self, _: ForcedDisplayUpdateEvent = None):
        self.safe_refresh_display()

    def safe_refresh_display(self):

        try:
            self.refresh()
        except Exception as e:
            logger.error("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception!\n({e})", fill="white")

    def _draw_dimmed_content(self, layout: HBox):
        now = GeoLocation().now()
        day = now.day

        # Screensaver logic: shift content based on day of month
        x_offset = day * 3
        y_offset = (day % 5) * 4

        layout.set_margins(x_offset, y_offset, 0, 0)
        layout.spacing = 10

        # Clock
        clock_string = self.formatter.format_dseg7_clock_string(
            now, self.display_content.show_blink_segment
        )
        clock_label = Label(
            clock_string, self.formatter.clock_font_pil(size=18), align="left"
        )
        layout.add_widget(clock_label)

        # Info Stack
        info_layout = VBox()
        info_layout.spacing = 0

        # Next Alarm
        if (
            self.display_content.has_next_alarm()
            and self.display_content.next_alarm_info.minutes_until_alarm()
            <= self.display_content.alarm_clock_context.config.alarm_preview_hours * 60
        ):
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = self.formatter.format_clock_string(alarm_time)
            alarm_label = Label(
                f"\uf49a {alarm_text}", self.formatter.info_font_pil(size=12)
            )
            info_layout.add_widget(alarm_label)

        # WiFi
        is_online = self.display_content.get_is_online()
        no_wifi_symbol = "\U000f05aa"
        wifi_text = "" if is_online else no_wifi_symbol
        wifi_label = Label(wifi_text, self.formatter.info_font_pil(size=14))
        info_layout.add_widget(wifi_label)

        layout.add_widget(info_layout)
        layout.add_widget(Spacer(), stretch=1)

    def _draw_normal_content(self, layout: HBox):
        layout.add_widget(Spacer(width=10))

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

        fg_color = self.formatter.foreground_color(color_type=ColorType.INHEX)

        clock_widget = ClockWidget(
            hour_str,
            minute_str,
            blink_char,
            self.display_content.show_blink_segment,
            fg_color,
            font=self.formatter.clock_font_pil(size=42),
        )
        layout.add_widget(clock_widget, stretch=3)

        # Vertical Line
        # line = QtWidgets.QWidget()
        # line.setFixedWidth(1)
        # line.setStyleSheet(f"background-color: {fg_color};")
        # layout.addWidget(line)
        # layout.addSpacing(10)

        # TODO: Implement Line widget or just use Spacer with draw?
        # For now, skip line or use a thin Label?
        # I'll skip the line for simplicity or add a custom Line widget later.
        layout.add_widget(Spacer(width=10))

        # --- Right: Info Stack ---
        info_layout = VBox()
        info_layout.spacing = 0
        info_layout.add_widget(Spacer(), stretch=1)

        # 1. Weather
        weather = self.display_content.current_weather
        if weather:
            temp = weather.temperature if weather is not None else None
            if temp is not None:
                weather_container = HBox()
                weather_container.spacing = 5

                symbol = weather.code.to_character() if weather.code else None
                if symbol:
                    symbol_label = Label(
                        symbol, self.formatter.weather_font_pil(size=16)
                    )
                    weather_container.add_widget(symbol_label)

                weather_label = Label(
                    f"{temp:.1f}°C", self.formatter.info_font_pil(size=12)
                )
                weather_container.add_widget(weather_label)

                info_layout.add_widget(weather_container)

        # 3. Playback
        playback_title = self.display_content.current_playback_title()
        if playback_title:
            if playback_title != self._last_playback_title:
                self._last_playback_title = playback_title
                self._playback_title_scroll_start_time = time.time()

            playback_container = HBox()
            playback_container.spacing = 5

            playback_symbol = Label("\uf2eb", self.formatter.info_font_pil(size=16))
            playback_container.add_widget(playback_symbol)

            playback_label = ScrollingLabel(
                playback_title,
                self.formatter.info_font_pil(size=12),
                fg_color,
                self._playback_title_scroll_start_time,
                self.display_content,
            )
            playback_container.add_widget(playback_label, stretch=1)

            info_layout.add_widget(playback_container)

        # 3. Next Alarm
        if (
            self.display_content.has_next_alarm()
            and self.display_content.next_alarm_info.minutes_until_alarm()
            <= self.display_content.alarm_clock_context.config.alarm_preview_hours * 60
        ):
            alarm_time = self.display_content.get_next_alarm()
            alarm_text = alarm_time.strftime("%H:%M")

            alarm_container = HBox()
            alarm_container.spacing = 5

            alarm_symbol = Label("\uf49a", self.formatter.info_font_pil(size=12))
            alarm_container.add_widget(alarm_symbol)

            alarm_label = Label(alarm_text, self.formatter.info_font_pil(size=12))
            alarm_container.add_widget(alarm_label)

            info_layout.add_widget(alarm_container)

        # 4. Volume
        if self.display_content.show_volume_meter:
            vol = self.display_content.current_volume()
            vol_label = Label(
                f"Vol: {int(vol * 100)}%", self.formatter.info_font_pil(size=12)
            )
            info_layout.add_widget(vol_label)

        info_layout.add_widget(Spacer(), stretch=1)
        layout.add_widget(info_layout, stretch=2)

    def _draw_default_view(self, layout: HBox):
        if self.formatter.be_gloomy():
            self._draw_dimmed_content(layout)
        else:
            self._draw_normal_content(layout)

    def _draw_alarm_view(self, layout: HBox):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service:
            return

        alarm = service.current_alarm

        # Main Container
        container = VBox()
        container.set_margins(10, 5, 10, 5)

        # Row 0: Header (Alarm Index)
        index = service.current_alarm_index + 1
        total = len(self.alarm_clock_context.config.alarm_definitions) + 1
        header_label = Label(
            f"ALARM {index}/{total}",
            self.formatter.info_font_pil(size=10),
            align="left",
        )
        container.add_widget(header_label)

        # Row 1: Content
        content_row = HBox()

        # Time (Big)
        time_str = f"{alarm.hour:02d}:{alarm.min:02d}"
        time_label = Label(
            time_str, self.formatter.info_font_pil(size=32), align="left"
        )
        content_row.add_widget(time_label, stretch=1)

        # Right Side Info
        right_col = VBox()

        # Active Status
        status_icon = "\uf205" if alarm.is_active else "\uf204"  # Toggle On/Off
        status_label = Label(
            status_icon, self.formatter.info_font_pil(size=20), align="right"
        )
        right_col.add_widget(status_label)

        # Days
        days_str = "New Alarm"
        if alarm.id is not None:
            try:
                days_str = alarm.to_day_string()
                if len(days_str) > 15:
                    days_str = days_str[:12] + "..."
            except:
                days_str = "Invalid"

        days_label = Label(
            days_str, self.formatter.info_font_pil(size=12), align="right"
        )
        right_col.add_widget(days_label)

        content_row.add_widget(right_col, stretch=1)
        container.add_widget(content_row, stretch=1)

        layout.add_widget(container, stretch=1)

    def _draw_alarm_edit_view(self, layout: HBox):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        current_prop = service.property_to_edit

        container = VBox()

        # Property Name
        prop_name = ""
        if isinstance(current_prop, AlarmProperty):
            prop_name = current_prop.name.replace("_", " ")
        elif isinstance(current_prop, EditorAction):
            prop_name = current_prop.value.upper()

        prop_label = Label(
            prop_name, self.formatter.info_font_pil(size=18), align="center"
        )
        container.add_widget(prop_label)

        # Current Value Preview (if not an action)
        if isinstance(current_prop, AlarmProperty):
            val = service.editing_session.get_current_value()
            val_str = str(val)
            # Format specific values
            if current_prop == AlarmProperty.RECURRING:
                # val is list of strings
                val_str = f"{len(val)} days"
            elif current_prop == AlarmProperty.AUDIO_EFFECT:
                val_str = val.title() if val else "None"

            val_label = Label(
                val_str, self.formatter.info_font_pil(size=12), align="center"
            )
            container.add_widget(val_label)

        layout.add_widget(container, stretch=1)

    def _draw_property_edit_view(self, layout: HBox):
        coordinator = self.alarm_clock_context.mode_coordinator
        service = coordinator.editing_service
        if not service or not service.editing_session:
            return

        current_prop = service.property_to_edit
        current_val = service.editing_session.get_current_value()

        container = VBox()

        # Property Name
        prop_name = (
            current_prop.name.replace("_", " ")
            if isinstance(current_prop, AlarmProperty)
            else ""
        )
        header = Label(
            f"SET {prop_name}", self.formatter.info_font_pil(size=10), align="center"
        )
        container.add_widget(header)

        # Value with arrows
        h_layout = HBox()
        h_layout.add_widget(Spacer(), stretch=1)

        left_arrow = Label(
            "\uf053", self.formatter.info_font_pil(size=16), align="center"
        )  # Chevron Left
        h_layout.add_widget(left_arrow)

        val_str = str(current_val)
        # Formatting
        if current_prop == AlarmProperty.RECURRING:
            # val is list of strings
            val_str = ", ".join([d[:3] for d in current_val])
        elif current_prop == AlarmProperty.AUDIO_EFFECT:
            val_str = current_val.title() if current_val else "None"
        elif current_prop == AlarmProperty.HOUR or current_prop == AlarmProperty.MIN:
            val_str = f"{current_val:02d}"

        val_label = Label(
            f" {val_str} ", self.formatter.info_font_pil(size=18), align="center"
        )
        h_layout.add_widget(val_label)

        right_arrow = Label(
            "\uf054", self.formatter.info_font_pil(size=16), align="center"
        )  # Chevron Right
        h_layout.add_widget(right_arrow)

        h_layout.add_widget(Spacer(), stretch=1)
        container.add_widget(h_layout)

        layout.add_widget(container, stretch=1)

    def draw_widget(self):
        self.formatter.update_formatter()
        # Reset scrolling state; widgets will set it to True if they need high refresh rate
        self.display_content.is_scrolling = False

        fg_color = self.formatter.foreground_color(color_type=ColorType.INHEX)
        bg_color = self.formatter.background_color(color_type=ColorType.INHEX)

        # Create PIL Image
        image = Image.new("RGB", (self.device.width, self.device.height), bg_color)
        draw = ImageDraw.Draw(image)

        # Main Layout
        layout = HBox()
        layout.set_margins(10, 0, 5, 0)
        layout.spacing = 0

        mode = (
            self.alarm_clock_context.mode_coordinator.current_mode_name
            if self.alarm_clock_context.mode_coordinator
            else ModeName.DEFAULT
        )

        if mode == ModeName.DEFAULT:
            self._draw_default_view(layout)
        elif mode == ModeName.ALARM_VIEW:
            self._draw_alarm_view(layout)
        elif mode == ModeName.ALARM_EDIT:
            self._draw_alarm_edit_view(layout)
        elif mode == ModeName.PROPERTY_EDIT:
            self._draw_property_edit_view(layout)

        # Layout and Render
        layout.set_geometry(0, 0, self.device.width, self.device.height)
        layout.render(image, draw)

        self.current_display_image = self.formatter.postprocess_image(image)

    def refresh(self):
        logger.debug("draw_widget: %sms", timeit(self.draw_widget, number=1) * 1000)
        # self.current_display_image is set in draw_widget
        try:
            self.device.display(self.current_display_image)
            if isinstance(self.device, luma_dummy):
                self.current_display_image.save(
                    display_shot_file,
                    format="png",
                )
        except AssertionError as e:
            pass


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
    d = Display(dev, dc, pc, DisplayFormatter(dc, s), s)
    d.refresh()
    image = d.current_display_image

    if is_on_hardware:
        time.sleep(10)
    else:
        save_file = display_shot_file
        image.save(save_file, format="png")
