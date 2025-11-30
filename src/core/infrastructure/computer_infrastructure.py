import logging
import traceback
from pynput import keyboard
from core.application.controls import Controls
from core.domain.events import AlarmTriggeredEvent
from core.domain.model import Config
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from core.infrastructure.events_infrastructure import (
    DeviceName,
    HwButtonEvent,
    HwRotaryEvent,
    RotaryDirection,
)

logger = logging.getLogger("tac.keyboard_buttons")


class ComputerInfrastructure(IBrightnessSensor):
    simulated_brightness: int = 10000

    def __init__(self):
        self.log = logging.getLogger(self.__class__.__name__)
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()

    def configure(self, controls: Controls):
        self.controls = controls
        self.config = controls.alarm_clock_context.config
        self.event_bus = controls.event_bus

    def on_press(self, key):
        logger.debug("pressed %s", key)
        if not hasattr(key, "char"):
            return
        try:
            if key.char == "1":
                self.event_bus.emit(
                    HwRotaryEvent(
                        DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE
                    )
                )
            if key.char == "2":
                self.event_bus.emit(
                    HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE)
                )
            if key.char == "3":
                self.event_bus.emit(HwButtonEvent(DeviceName.MODE_BUTTON))
            if key.char == "4":
                self.event_bus.emit(HwButtonEvent(DeviceName.INVOKE_BUTTON))
            if key.char == "5":
                brightness_examples = [0, 1, 3, 10, 10000]
                self.simulated_brightness = brightness_examples[
                    (brightness_examples.index(self.simulated_brightness) + 1)
                    % len(brightness_examples)
                ]
                logger.info("simulated brightness: %s", self.simulated_brightness)
            if key.char == "6":
                self.controls._ring_alarm(self.config.get_default_alarm_definition())
            if key.char == "7":
                ad = self.config.get_default_alarm_definition()
                ad.audio_effect.audio_stream.stream_url = "invalid_stream_url"
                self.controls._ring_alarm(ad)

        except Exception:
            logger.warning("%s", traceback.format_exc())

    def get_room_brightness(self) -> float:
        return self.simulated_brightness

    def stop(self):
        self.listener.stop()
