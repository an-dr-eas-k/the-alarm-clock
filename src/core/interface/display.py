import datetime
from enum import Enum
import logging
import traceback
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import ImageFont, Image

from core.domain import (
    AlarmClockState,
    AlarmDefinition,
    AlarmEditorMode,
    Config,
    DefaultMode,
    DisplayContent,
    TACEvent,
    TACEventSubscriber,
    PlaybackContent,
    SpotifyAudioEffect,
    TacMode,
    VisualEffect,
)
from core.interface.default import (
    ClockPresenter,
    NextAlarmPresenter,
    PlaybackTitlePresenter,
    VolumeMeterPresenter,
    WeatherStatusPresenter,
    WifiStatusPresenter,
)
from core.interface.presenter import BackgroundPresenter, Presenter, RefreshPresenter
from utils.drawing import (
    grayscale_to_color,
    ImageComposition,
)
from utils.extensions import get_job_arg, get_timedelta_to_alarm, respect_ranges
from utils.geolocation import GeoLocation

from resources.resources import fonts_dir, display_shot_file

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


class ModeComposer:
    def __init__(
        self,
        formatter: DisplayFormatter,
        content: DisplayContent,
        size: tuple[int, int],
    ) -> None:
        self.formatter = formatter
        self.display_content = content
        self.size = size

    def compose(self, composition: ImageComposition):
        current_state = self.display_content.state.state_machine.current_state
        if isinstance(current_state, DefaultMode):
            self.compose_default(composition, current_state)

        elif isinstance(current_state, AlarmEditorMode):
            self.compose_alarm_changer(composition, current_state)

    def compose_alarm_changer(
        self, composition: ImageComposition, mode: AlarmEditorMode
    ):
        composition.add_image(
            BackgroundPresenter(self.formatter, self.display_content, self.size)
        )

        alarm_definition: AlarmDefinition = (
            self.display_content.state.config.alarm_definitions[mode.alarm_index]
        )

    def compose_default(self, composition: ImageComposition, mode: DefaultMode):
        composition.add_image(
            BackgroundPresenter(self.formatter, self.display_content, self.size)
        )

        composition.add_image(
            ClockPresenter(
                self.formatter,
                self.display_content,
                lambda width, height: (
                    (self.size[0] - width),
                    int((self.size[1] - height) / 2),
                ),
            )
        )
        composition.add_image(
            NextAlarmPresenter(
                self.formatter,
                self.display_content,
                lambda _, height: (2, self.size[1] - height - 2),
            )
        )
        composition.add_image(
            PlaybackTitlePresenter(
                self.formatter,
                self.display_content,
                lambda _, height: (2, self.size[1] - height - 2),
            )
        )
        composition.add_image(
            WeatherStatusPresenter(
                self.formatter,
                self.display_content,
                lambda _, _1: (2, 4),
            )
        )
        composition.add_image(
            WifiStatusPresenter(
                self.formatter,
                self.display_content,
                lambda _, _1: (2, 2),
            )
        )
        composition.add_image(
            RefreshPresenter(
                self.formatter,
                self.display_content,
                lambda width, _1: (self.size[0] - width, 2),
            )
        )
        composition.add_image(
            VolumeMeterPresenter(
                self.formatter, self.display_content, (10, self.size[1])
            )
        )


class Display(TACEventSubscriber):

    device: luma_device
    display_content: DisplayContent
    current_display_image: Image.Image

    def __init__(
        self,
        device: luma_device,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        state: AlarmClockState,
    ) -> None:
        self.device = device
        logger.info("device mode: %s", self.device.mode)
        self.display_content = display_content
        self.playback_content = playback_content
        self.state = state
        self.formatter = DisplayFormatter(self.display_content, self.state)
        self.composable_presenters = ImageComposition(
            Image.new(mode=self.device.mode, size=self.device.size, color="black")
        )

        self.mode_presenter = ModeComposer(
            self.formatter, self.display_content, self.device.size
        )

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if isinstance(observation.subscriber, DisplayContent):
            self.update_from_display_content(observation, observation.subscriber)

    def update_from_display_content(self, _1: TACEvent, _2: DisplayContent):
        try:
            self.adjust_display()
        except Exception as e:
            logger.warning("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception! ({e})", fill="white")

    def adjust_display(self):
        logger.debug("refreshing display...")
        start_time = GeoLocation().now()
        self.device.contrast(16)
        self.formatter.update_formatter()
        self.composable_presenters.debug = self.state.config.debug_level >= 10
        self.display_content.is_scrolling = False

        if self.formatter.clear_display():
            logger.info("clearing display")
            self.device.clear()

        self.current_display_image = self.present()
        self.device.display(self.current_display_image)
        if isinstance(self.device, luma_dummy):
            self.current_display_image.save(
                display_shot_file,
                format="png",
            )

        logger.debug(
            "refreshed display in %dms",
            (GeoLocation().now() - start_time).total_seconds() * 1000,
        )

    def present(self) -> Image.Image:
        self.mode_presenter.compose(self.composable_presenters)
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
    d = Display(dev, dc, pc, s)
    d.handle(TACEvent(event_publisher=dc, reason="init"))
    image = d.current_display_image

    # with canvas(dev) as draw:
    # 	draw.text((20, 20), "Hello World!", fill="white")

    if is_on_hardware:
        time.sleep(10)
    else:
        save_file = display_shot_file
        image.save(save_file, format="png")
