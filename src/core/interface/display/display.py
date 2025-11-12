import io
import logging
import traceback
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import Image

from PyQt5 import QtWidgets, QtCore, QtGui

from core.domain.events import (
    ForcedDisplayUpdateEvent,
)
from core.domain.model import (
    AlarmClockContext,
    Config,
    DisplayContent,
    DisplayContentProvider,
    PlaybackContent,
    SpotifyStream,
)
from core.infrastructure.event_bus import EventBus
from core.interface.display.format import DisplayFormatter
from core.interface.display.presenter import (
    BackgroundPresenter,
    RefreshPresenter,
)
from core.interface.display.editor.default import (
    AlarmActiveStatusPresenter,
    AlarmCancelPresenter,
    AlarmUpdatePresenter,
    ClockPresenter,
    NextAlarmPresenter,
    PlaybackTitlePresenter,
    VolumeMeterPresenter,
    WeatherStatusPresenter,
    WifiStatusPresenter,
    AlarmNamePresenter,
    AlarmTimePresenter,
    AlarmDatePresenter,
    AlarmAudioEffectPresenter,
)
from utils.drawing import ImageComposition

from utils.geolocation import GeoLocation

from resources.resources import display_shot_file

logger = logging.getLogger("tac.display")


class Display(DisplayContentProvider):

    device: luma_device
    display_content: DisplayContent

    def __init__(
        self,
        device: luma_device,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        alarm_clock_context: AlarmClockContext,
        event_bus: EventBus = None,
    ) -> None:
        self.device = device
        logger.info("device mode: %s", self.device.mode)
        self.display_content = display_content
        self.playback_content = playback_content
        self.alarm_clock_context = alarm_clock_context
        self.event_bus = event_bus
        self.formatter = DisplayFormatter(
            self.display_content, self.alarm_clock_context
        )
        self.composable_presenters = ImageComposition(
            Image.new(mode=self.device.mode, size=self.device.size, color="black")
        )

        # self.composable_presenters.add_image(
        #     BackgroundPresenter(self.formatter, self.display_content, self.device.size)
        # )
        # self.compose_default()
        # self.compose_alarm_changer()
        # self.composable_presenters.add_image(
        #     RefreshPresenter(
        #         self.formatter,
        #         self.display_content,
        #         lambda width, _1: (self.device.size[0] - width, 2),
        #     )
        # )
        self.app = QtWidgets.QApplication([])
        self.event_bus.on(ForcedDisplayUpdateEvent)(self._forced_update)

    def compose_alarm_changer(self):

        aup = AlarmUpdatePresenter(
            self.formatter, self.display_content, lambda _, _2: (2, 1)
        )
        acp = AlarmCancelPresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (aup.get_bounding_box()[2] + 4, 1),
        )
        anp = AlarmNamePresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (
                acp.get_bounding_box()[2] + 10,
                4,
            ),
        )
        asp = AlarmActiveStatusPresenter(
            self.formatter,
            self.display_content,
            lambda img_width, _2: (self.device.width - img_width - 10, 2),
        )
        atp = AlarmTimePresenter(
            self.formatter,
            self.display_content,
            lambda _, _2: (2, aup.get_bounding_box()[3] + 2),
        )
        awp = AlarmDatePresenter(
            self.formatter,
            self.display_content,
            lambda _, img_height: (
                atp.get_bounding_box()[2] + 5,
                atp.get_bounding_box()[3] - img_height - 2,
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

        self.composable_presenters.add_image(aup)
        self.composable_presenters.add_image(acp)
        self.composable_presenters.add_image(asp)
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
                self.event_bus,
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

    def _forced_update(self, _: ForcedDisplayUpdateEvent):
        try:
            self.refresh()
        except Exception as e:
            logger.warning("%s", traceback.format_exc())
            with canvas(self.device) as draw:
                draw.text((20, 20), f"exception! ({e})", fill="white")

    def draw_widget(self) -> Image.Image:
        self.widget = QtWidgets.QFrame()
        self.widget.setFixedSize(self.device.width, self.device.height)
        self.widget.setStyleSheet("background-color: black; color: white;")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(2, 2, 2, 2)  # Add padding

        clock_string = self.formatter.format_clock_string(
            GeoLocation().now(), self.display_content.show_blink_segment
        )
        label = QtWidgets.QLabel(clock_string)
        label.setFont(QtGui.QFont("Arial", 16))
        layout.addWidget(label, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)

        # button = QtWidgets.QPushButton("I was never on screen")
        # layout.addWidget(button)

        # checkbox = QtWidgets.QCheckBox("This is also a widget")
        # layout.addWidget(checkbox)

        pixmap = self.widget.grab()

        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")

        pil_image = Image.open(io.BytesIO(buffer.data()))
        return pil_image

    def present_my(self) -> Image.Image:
        self.device.contrast(16)
        self.formatter.update_formatter()
        self.composable_presenters.debug = (
            self.alarm_clock_context.config.debug_level >= 10
        )
        self.display_content.is_scrolling = False

        if self.formatter.clear_display():
            logger.info("clearing display")
            self.device.clear()
        return self.present()

    def refresh(self):
        logger.debug("refreshing display...")
        start_time = GeoLocation().now()
        # self.current_display_image = self.present_my()
        self.current_display_image = self.draw_widget()
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
    s = AlarmClockContext(c=c)
    pc = PlaybackContent(alarm_clock_context=s)
    pc.audio_stream = SpotifyStream()
    dc = DisplayContent(alarm_clock_context=s, playback_content=pc)
    dc.show_blink_segment = True
    d = Display(dev, dc, pc, s)
    d.refresh()
    image = d.current_display_image

    # with canvas(dev) as draw:
    # 	draw.text((20, 20), "Hello World!", fill="white")

    if is_on_hardware:
        time.sleep(10)
    else:
        save_file = display_shot_file
        image.save(save_file, format="png")
