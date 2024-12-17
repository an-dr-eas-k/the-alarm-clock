import logging
import traceback
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import Image

from core.domain import (
    AlarmClockState,
    Config,
    DisplayContent,
    TACEvent,
    TACEventSubscriber,
    PlaybackContent,
    SpotifyAudioEffect,
)
from core.interface.default import (
    ClockPresenter,
    NextAlarmPresenter,
    PlaybackTitlePresenter,
    VolumeMeterPresenter,
    WeatherStatusPresenter,
    WifiStatusPresenter,
    AlarmNamePresenter,
    AlarmTimePresenter,
    AlarmWeekdaysPresenter,
    AlarmAudioEffectPresenter,
)
from core.interface.format import DisplayFormatter
from core.interface.presenter import (
    BackgroundPresenter,
    RefreshPresenter,
)
from utils.drawing import ImageComposition

from utils.geolocation import GeoLocation

from resources.resources import display_shot_file

logger = logging.getLogger("tac.display")


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

        self.composable_presenters.add_image(
            BackgroundPresenter(self.formatter, self.display_content, self.device.size)
        )
        self.compose_default()
        self.compose_alarm_changer()
        self.composable_presenters.add_image(
            RefreshPresenter(
                self.formatter,
                self.display_content,
                lambda width, _1: (self.device.size[0] - width, 2),
            )
        )

    def compose_alarm_changer(self):

        anp = AlarmNamePresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (2, 2),
        )
        atp = AlarmTimePresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (2, anp.get_bounding_box()[3] + 2),
        )
        awp = AlarmWeekdaysPresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (
                atp.get_bounding_box()[2] + 5,
                anp.get_bounding_box()[3] + 2,
            ),
        )
        aep = AlarmAudioEffectPresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (
                2,
                max(awp.get_bounding_box()[3], atp.get_bounding_box()[3]) + 2,
            ),
        )
        self.composable_presenters.add_image(anp)
        self.composable_presenters.add_image(atp)
        self.composable_presenters.add_image(awp)
        self.composable_presenters.add_image(aep)

        # composition.add_image(
        #     AlarmVisualEffectPresenter(
        #         self.formatter,
        #         alarm_definition,
        #         lambda _, _2: (100, 22),
        #     )
        # )
        # composition.add_image(
        #     AlarmActiveStatusPresenter(
        #         self.formatter,
        #         alarm_definition,
        #         lambda _, height: (2, height + 12),
        #     )
        # )

    def compose_default(self):

        self.composable_presenters.add_image(
            ClockPresenter(
                self.formatter,
                self.display_content,
                lambda width, height: (
                    (self.device.size[0] - width),
                    int((self.device.size[1] - height) / 2),
                ),
            )
        )
        self.composable_presenters.add_image(
            NextAlarmPresenter(
                self.formatter,
                self.display_content,
                lambda _, height: (2, self.device.size[1] - height - 2),
            )
        )
        self.composable_presenters.add_image(
            PlaybackTitlePresenter(
                self.formatter,
                self.display_content,
                lambda _, height: (2, self.device.size[1] - height - 2),
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
                self.formatter, self.display_content, (10, self.device.size[1])
            )
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
