import logging
from PIL import ImageFont, Image, ImageOps

from core.domain.events import AudioEffectEvent
from core.domain.mode_coordinator import AlarmEditMode
from core.domain.model import (
    DisplayContent,
    PlaybackContent,
)
from core.infrastructure.event_bus import EventBus
from core.interface.display.display import DisplayFormatter
from core.interface.display.presenter import (
    AlarmEditorPresenter,
    DefaultPresenter,
    ScrollingPresenter,
    SimpleTextPresenter,
)
from utils.analog_clock import AnalogClockGenerator
from utils.drawing import (
    PresentationFont,
    get_concat_h_multi_blank,
    get_concat_v,
    text_to_image,
)
from utils.geolocation import GeoLocation

from resources.resources import weather_icons_dir

logger = logging.getLogger("tac.display.default")


class AlarmNamePresenter(AlarmEditorPresenter):
    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        position,
    ) -> None:
        super().__init__(formatter, content, position)

    def draw(self) -> Image.Image:
        font = self.formatter.default_font(size=15)

        return text_to_image(
            self.get_alarm_definition().alarm_name,
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )


class AlarmTimePresenter(AlarmEditorPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def draw(self) -> Image.Image:
        machine_state = self.machine_state(AlarmEditMode)
        font = self.formatter.default_font(size=20)
        alarm_def = self.get_alarm_definition()
        if machine_state is None or not machine_state.is_in_edit_mode(["hour", "min"]):
            return text_to_image(
                alarm_def.to_time_string(),
                font,
                fg_color=self.formatter.foreground_color(),
                bg_color=self.formatter.background_color(),
            )

        hour_image = text_to_image(
            f"{alarm_def.hour:02}",
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
        if machine_state is not None and machine_state.is_in_edit_mode(["hour"]):
            hour_image = ImageOps.expand(hour_image, border=1, fill="white")

        minute_image = text_to_image(
            f"{alarm_def.min:02}",
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
        if machine_state is not None and machine_state.is_in_edit_mode(["min"]):
            minute_image = ImageOps.expand(minute_image, border=1, fill="white")

        return get_concat_h_multi_blank(
            [
                hour_image,
                text_to_image(
                    ":",
                    font,
                    fg_color=self.formatter.foreground_color(),
                    bg_color=self.formatter.background_color(),
                ),
                minute_image,
            ],
            self.formatter.background_color(),
        )


class AlarmDatePresenter(AlarmEditorPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def draw(self) -> Image.Image:
        machine_state = self.machine_state(AlarmEditMode)
        font = self.formatter.default_font(size=15)
        alarm_def = self.get_alarm_definition()
        day_string = alarm_def.to_day_string()
        day_image = text_to_image(
            day_string,
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
        if machine_state is None or not machine_state.is_in_edit_mode(
            ["recurring", "onetime"]
        ):
            return day_image

        return ImageOps.expand(day_image, border=1, fill="white")


class AlarmVisualEffectPresenter(SimpleTextPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(
            formatter,
            content,
            position,
            lambda ad: ("N" if ad.visual_effect is None else "A"),
            "visual_effect",
        )


class AlarmAudioEffectPresenter(SimpleTextPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(
            formatter,
            content,
            position,
            lambda ad: ad.audio_effect.title(),
            "audio_effect",
        )


class AlarmActiveStatusPresenter(SimpleTextPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(
            formatter,
            content,
            position,
            lambda ad: ("\U0000f1e2" if ad.is_active else "\U0000eed6"),
            "is_active",
        )


class AlarmUpdatePresenter(SimpleTextPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(
            formatter, content, position, lambda _: ("\U0000f058"), "update"
        )


class AlarmCancelPresenter(SimpleTextPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(
            formatter, content, position, lambda _: ("\U000f073a"), "cancel"
        )


class ClockPresenter(DefaultPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position: callable
    ) -> None:
        super().__init__(formatter, content, position)
        self.analog_clock = AnalogClockGenerator(
            hour_markings_width=1,
            hour_markings_length=1,
            hour_hand_width=4,
            minute_hand_width=2,
            second_hand_width=0,
        )

    def draw_analog_clock(self) -> Image.Image:
        day = GeoLocation().now().day

        self.analog_clock.hour_hand_color = self.analog_clock.minute_hand_color = (
            self.analog_clock.hour_markings_color
        ) = self.analog_clock.origin_color = self.formatter.foreground_color()
        self.analog_clock.background_color = self.formatter.background_color()

        analog_clock = Image.new(
            "RGBA", (64 + day, 64), color=self.formatter.background_color()
        )
        analog_clock.paste(
            self.analog_clock.get_current_clock(
                now=GeoLocation().now(), clock_radius=31
            )
        )
        return analog_clock

    def draw(self) -> Image.Image:
        if (
            self.formatter.highly_dimmed()
            and self.formatter.alarm_clock_context.config.use_analog_clock
        ):
            return self.draw_analog_clock()

        font = self.formatter.clock_font()
        clock_string = self.formatter.format_clock_string(
            GeoLocation().now(), self.content.show_blink_segment
        )
        clock_image = text_to_image(
            clock_string,
            font,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
        return self.formatter.postprocess_image(
            clock_image.resize(
                [int(clock_image.width * 0.95), clock_image.height],
                resample=Image.NEAREST,
            )
        )


class VolumeMeterPresenter(DefaultPresenter):
    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        size: tuple[int, int],
        position=None,
    ) -> None:
        super().__init__(formatter, content, position)
        self.size = size

    def is_present(self):
        return super().is_present() and self.content.show_volume_meter

    def draw(self) -> Image.Image:
        if not self.content.show_volume_meter:
            return self.empty_image

        fg = Image.new(
            "RGB",
            (self.size[0], int(self.size[1] * self.content.current_volume())),
            color=self.formatter.foreground_color(),
        )
        bg = Image.new(
            "RGB",
            (self.size[0], int(self.size[1] * (1.0 - self.content.current_volume()))),
            color=self.formatter.background_color(),
        )
        return get_concat_v(bg, fg, self.formatter.background_color())


class WifiStatusPresenter(DefaultPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self):
        return (
            super().is_present()
            and not self.content.show_volume_meter
            and not self.content.get_is_online()
        )

    def draw(self) -> Image.Image:
        no_wifi_symbol = "\U000f05aa"
        font_size = 30
        min_value = 2
        if self.formatter.highly_dimmed():
            no_wifi_symbol = "!"
            font_size = 15
            min_value = 1

        font = ImageFont.truetype(self.font_file_nerd, font_size)

        return text_to_image(
            no_wifi_symbol,
            font,
            fg_color=self.formatter.foreground_color(min_value=min_value),
            bg_color=self.formatter.background_color(),
        )


class PlaybackTitlePresenter(ScrollingPresenter):

    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        event_bus: EventBus,
        position,
    ) -> None:
        super().__init__(formatter, content, 70, position)
        self.event_bus = event_bus
        self.event_bus.on(AudioEffectEvent)(self._audio_effect)

    def _audio_effect(self, event: AudioEffectEvent):
        if event.audio_effect is not None:
            self.rewind_scroller()

    def is_present(self) -> bool:
        return (
            super().is_present()
            and not self.content.show_volume_meter
            and self.content.current_playback_title() is not None
        )

    def draw(self) -> Image.Image:
        return get_concat_h_multi_blank(
            [self.compose_note_symbol(), self.scroll(self.compose_playback_title())],
            self.formatter.background_color(),
        )

    def compose_playback_title(self) -> Image.Image:
        title_font = ImageFont.truetype(self.font_file_nerd, 18)

        return text_to_image(
            self.content.current_playback_title(),
            title_font,
            fg_color=self.formatter.foreground_color(min_value=2),
            bg_color=self.formatter.background_color(),
        )

    def compose_note_symbol(self) -> Image.Image:
        note_font = ImageFont.truetype(self.font_file_nerd, 22)

        note_symbol = "\U000f075a"
        note_symbol_img = text_to_image(
            note_symbol,
            note_font,
            fg_color=self.formatter.foreground_color(min_value=2),
            bg_color=self.formatter.background_color(),
        )

        return get_concat_h_multi_blank(
            [note_symbol_img, Image.new(mode="RGB", size=(3, 0))],
            self.formatter.background_color(),
        )


class NextAlarmPresenter(DefaultPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self) -> bool:
        return (
            super().is_present()
            and self.content.current_playback_title() is None
            and not self.content.show_volume_meter
            and self.content.get_timedelta_to_alarm().total_seconds() / 3600
            <= self.content.alarm_clock_context.config.alarm_preview_hours
        )

    def draw(self) -> Image.Image:
        font_nerd = ImageFont.truetype(self.font_file_nerd, 20)
        font_7segment = ImageFont.truetype(self.font_file_7segment, 13)

        next_alarm_string = self.formatter.format_clock_string(
            self.content.get_next_alarm()
        )
        next_alarm_img = text_to_image(
            next_alarm_string,
            font_7segment,
            fg_color=self.formatter.foreground_color(min_value=2),
            bg_color=self.formatter.background_color(),
        )
        alarm_symbol = "\U000f0020"
        alarm_symbol_img = text_to_image(
            alarm_symbol,
            font_nerd,
            fg_color=self.formatter.foreground_color(min_value=2),
            bg_color=self.formatter.background_color(),
        )

        return get_concat_h_multi_blank(
            [
                alarm_symbol_img,
                Image.new(mode="RGB", size=(3, 0)),
                next_alarm_img,
            ],
            self.formatter.background_color(),
        )


class WeatherStatusPresenter(DefaultPresenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)
        self.font_file_weather = PresentationFont.weather_font

    def is_present(self):
        return (
            super().is_present()
            and not self.content.show_volume_meter
            and not self.formatter.highly_dimmed()
            and self.content.get_is_online()
            and self.content.current_weather is not None
        )

    def draw(self) -> Image.Image:
        weather = self.content.current_weather
        weather_character = weather.code.to_character()
        font_weather = PresentationFont.get_font(self.font_file_weather, 20)
        font_7segment = PresentationFont.get_font(self.font_file_7segment, 24)

        weather_image = text_to_image(
            weather_character,
            font_weather,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )
        formatter = "{:.1f}"
        desired_length = 4
        if abs(weather.temperature) >= 10:
            formatter = "{:.0f}"
            desired_length = 3

        temperature_str = self.formatter.format_dseg7_string(
            dseg7=formatter.format(weather.temperature), desired_length=desired_length
        )

        temperature_image = text_to_image(
            text=temperature_str,
            font=font_7segment,
            fg_color=self.formatter.foreground_color(),
            bg_color=self.formatter.background_color(),
        )

        width = int(0.6 * weather_image.width) + temperature_image.width
        height = int(0.6 * weather_image.height) + temperature_image.height
        dst = Image.new("RGB", [width, height], color=self.formatter.background_color())
        x = int(0.6 * weather_image.width)
        y = int(0.6 * weather_image.height)
        dst.paste(temperature_image, (x, y))
        dst.paste(weather_image, (0, 0))
        return dst
