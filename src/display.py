import datetime
from enum import Enum
import logging
import os
import traceback
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import ImageFont, Image

from domain import (
    AlarmClockState,
    AlarmDefinition,
    Config,
    DisplayContent,
    Mode,
    Observation,
    Observer,
    PlaybackContent,
    SpotifyAudioEffect,
    TACMode,
    VisualEffect,
)
from gpi import get_room_brightness
from utils.analog_clock import AnalogClockGenerator
from utils.drawing import (
    get_concat_h_multi_blank,
    get_concat_v,
    grayscale_to_color,
    text_to_image,
    ComposableImage,
    ImageComposition,
    Scroller,
)
from utils.extensions import get_job_arg, get_timedelta_to_alarm
from utils.geolocation import GeoLocation

from resources.resources import fonts_dir, weather_icons_dir

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
    _latest_room_brightness: float

    def __init__(self, content: DisplayContent, config: Config):
        self.display_content = content
        self.config = config

    def clock_font(self):
        return self._clock_font

    def clear_display(self):
        clear_display = self._clear_display
        self._clear_display = False
        return clear_display

    def highly_dimmed(self):
        return self._latest_room_brightness < 0.01

    def update_formatter(self, room_brightness: float):
        self._latest_room_brightness = room_brightness
        self.adjust_display(room_brightness)
        logger.debug(
            "room_brightness: %s, time_delta_to_alarm: %sh, display_formatter: %s",
            room_brightness,
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
        grayscale_16 = DisplayFormatter.respect_ranges(color, min_value, max_value)

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

    def respect_ranges(value: float, min_value: int = 0, max_value: int = 15) -> int:
        return int(max(min_value, min(max_value, value)))

    def get_grayscale_value(
        self, room_brightness: float, min_value: int = 0, max_value: int = 15
    ) -> int:
        x = max_value
        if room_brightness < 15:
            x = 10
        if room_brightness < 6:
            x = 7
        if room_brightness < 2:
            x = 3

        if self.highly_dimmed():
            x = 0
        return DisplayFormatter.respect_ranges(x, min_value, max_value)

    def adjust_display(self, room_brightness: float):
        self.adjust_display_by_room_brightness(room_brightness)
        self.adjust_display_by_alarm()

    def adjust_display_by_room_brightness(self, room_brightness: float):
        self._background_grayscale_16 = 0
        self._foreground_grayscale_16 = self.get_grayscale_value(
            room_brightness, min_value=1
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
        blink_segment = self.config.blink_segment if show_blink_segment else " "
        clock_string = clock.strftime(
            self.config.clock_format_string.replace("<blinkSegment>", blink_segment)
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


class Presenter(Observer, ComposableImage):
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


class ScrollingPresenter(Presenter):
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
        self._scroller = Scroller(self.canvas_width, 0, 2)

    def rewind_scroller(self):
        self._scroller.rewind()

    def scroll(self, image: Image.Image) -> Image.Image:
        return self._scroller.tick(image)


class BackgroundPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, device: luma_device
    ) -> None:
        super().__init__(formatter, content)
        self._device = device

    def is_present(self) -> bool:
        return True

    def draw(self):
        return Image.new(
            "RGB", self._device.size, color=self.formatter.background_color()
        )


class ClockPresenter(Presenter):
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

    def is_present(self) -> bool:
        return True

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
        if self.formatter.highly_dimmed() and self.formatter.config.use_analog_clock:
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


class VolumeMeterPresenter(Presenter):
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
        return self.content.show_volume_meter

    def draw(self) -> Image.Image:
        if not self.content.show_volume_meter:
            return self.empty_image

        fg = Image.new(
            "RGB",
            (self.size[0], int(self.size[1] * self.content.current_volume())),
            color="white",
        )
        bg = Image.new(
            "RGB",
            (self.size[0], int(self.size[1] * (1.0 - self.content.current_volume()))),
            color=self.formatter.background_color(),
        )
        return get_concat_v(bg, fg)


class WifiStatusPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self):
        return (
            True
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
        position,
    ) -> None:
        super().__init__(formatter, content, 90, position)
        content.playback_content.attach(self)

    def update(self, observation: Observation):
        super().update(observation)
        if (
            True
            and isinstance(observation.observable, PlaybackContent)
            and observation.property_name == "audio_effect"
        ):
            self.rewind_scroller()

    def is_present(self) -> bool:
        return (
            True
            and not self.content.show_volume_meter
            and self.content.current_playback_title() is not None
        )

    def draw(self) -> Image.Image:
        return self.scroll(self.compose_playback_title())

    def compose_playback_title(self) -> Image.Image:
        font_nerd = ImageFont.truetype(self.font_file_nerd, 27)
        font_7segment = ImageFont.truetype(self.font_file_7segment, 22)

        title = text_to_image(
            self.formatter.format_dseg7_string(self.content.current_playback_title()),
            font_7segment,
            fg_color=self.formatter.foreground_color(min_value=2),
            bg_color=self.formatter.background_color(),
        )

        note_symbol = "\U000f075a"
        note_symbol_img = text_to_image(
            note_symbol,
            font_nerd,
            fg_color=self.formatter.foreground_color(min_value=2),
            bg_color=self.formatter.background_color(),
        )

        return get_concat_h_multi_blank(
            [
                note_symbol_img,
                Image.new(mode="RGBA", size=(3, 0), color=(0, 0, 0, 0)),
                title,
            ]
        )


class NextAlarmPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)

    def is_present(self) -> bool:
        return (
            True
            and self.content.current_playback_title() is None
            and not self.content.show_volume_meter
            and self.content.get_timedelta_to_alarm().total_seconds() / 3600
            <= self.content.state.configuration.alarm_preview_hours
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
                Image.new(mode="RGBA", size=(3, 0), color=(0, 0, 0, 0)),
                next_alarm_img,
            ]
        )


class WeatherStatusPresenter(Presenter):
    def __init__(
        self, formatter: DisplayFormatter, content: DisplayContent, position
    ) -> None:
        super().__init__(formatter, content, position)
        self.font_file_weather = f"{weather_icons_dir}/weathericons-regular-webfont.ttf"

    def is_present(self):
        return (
            True
            and not self.content.show_volume_meter
            and not self.formatter.highly_dimmed()
            and self.content.get_is_online()
            and self.content.current_weather is not None
        )

    def draw(self) -> Image.Image:
        weather = self.content.current_weather
        weather_character = weather.code.to_character()
        font_weather = ImageFont.truetype(self.font_file_weather, 20)
        font_7segment = ImageFont.truetype(self.font_file_7segment, 24)

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


class ModePresenter(Presenter):
    def __init__(self, formatter: DisplayFormatter, content: DisplayContent) -> None:
        super().__init__(formatter, content)

    def draw(self) -> Image.Image:
        if self.content.mode_state.mode_0 == TACMode.ModesOnLevel0.AlarmChanger:
            # for alarm in self.content.state.configuration.alarm_definitions:
            #     alarm.
            pass


class Display(Observer):

    device: luma_device
    display_content: DisplayContent
    current_display_image: Image.Image

    def __init__(
        self,
        device: luma_device,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        config: Config,
    ) -> None:
        self.device = device
        logger.info("device mode: %s", self.device.mode)
        self.display_content = display_content
        self.playback_content = playback_content
        self.config = config
        self.formatter = DisplayFormatter(self.display_content, self.config)
        self.composable_presenters = ImageComposition(
            Image.new(mode=self.device.mode, size=self.device.size, color="black")
        )

        self.composable_presenters.add_image(
            BackgroundPresenter(self.formatter, self.display_content, self.device)
        )

        self.composable_presenters.add_image(
            ClockPresenter(
                self.formatter,
                self.display_content,
                lambda width, height: (
                    (device.width - width),
                    int((device.height - height) / 2),
                ),
            )
        )
        self.composable_presenters.add_image(
            NextAlarmPresenter(
                self.formatter,
                self.display_content,
                lambda _, height: (2, device.height - height - 2),
            )
        )
        self.composable_presenters.add_image(
            PlaybackTitlePresenter(
                self.formatter,
                self.display_content,
                lambda _, height: (2, device.height - height - 2),
            )
        )
        self.composable_presenters.add_image(
            WeatherStatusPresenter(
                self.formatter,
                self.display_content,
                lambda _, _1: (2, 4),
            )
        )
        self.composable_presenters.add_image(
            WifiStatusPresenter(
                self.formatter,
                self.display_content,
                lambda _, _1: (2, 2),
            )
        )
        self.composable_presenters.add_image(
            VolumeMeterPresenter(
                self.formatter, self.display_content, (10, self.device.height)
            )
        )
        self.mode_presenter = ModePresenter(self.formatter, self.display_content)

    def update(self, observation: Observation):
        super().update(observation)
        if isinstance(observation.observable, DisplayContent):
            self.update_from_display_content(observation, observation.observable)

    def update_from_display_content(self, _1: Observation, _2: DisplayContent):
        try:
            self.adjust_display()
        except Exception as e:
            logger.warning("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception! ({e})", fill="white")

    def adjust_display(self):
        self.device.contrast(16)
        room_brightness = get_room_brightness()
        self.formatter.update_formatter(room_brightness)

        if self.formatter.clear_display():
            logger.info("clearing display")
            self.device.clear()

        self.current_display_image = self.present()
        self.device.display(self.current_display_image)
        if isinstance(self.device, luma_dummy):
            self.current_display_image.save(
                f"{os.path.dirname(os.path.realpath(__file__))}/../../display_test.png",
                format="png",
            )

    def present(self) -> Image.Image:
        if self.display_content.mode_state.is_active():
            pass
            # im.paste(self.mode_presenter.draw(), (0, 0))
            # return im

        self.composable_presenters.refresh()
        return self.composable_presenters()


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
    s = AlarmClockState(c=c)
    pc = PlaybackContent(state=s)
    pc.audio_effect = SpotifyAudioEffect()
    pc.is_streaming = True
    dc = DisplayContent(state=s, playback_content=pc)
    dc.show_blink_segment = True
    d = Display(dev, dc, pc, s.configuration)
    d.update(Observation(observable=dc, reason="init"))
    image = d.current_display_image

    # with canvas(dev) as draw:
    # 	draw.text((20, 20), "Hello World!", fill="white")

    if is_on_hardware:
        time.sleep(10)
    else:
        save_file = (
            f"{os.path.dirname(os.path.realpath(__file__))}/../../display_test.png"
        )
        image.save(save_file, format="png")
