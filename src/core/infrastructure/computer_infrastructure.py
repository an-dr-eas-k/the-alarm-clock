import logging
import traceback
from pynput import keyboard
from core.domain.model import HwButton
from core.infrastructure.brightness_sensor import IBrightnessSensor
from utils.events import TACEventPublisher


logger = logging.getLogger("tac.keyboard_buttons")


class ComputerInfrastructure(TACEventPublisher, IBrightnessSensor):
    simulated_brightness: int = 10000

    def __init__(self):
        super().__init__()
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()
        self.log = logging.getLogger(self.__class__.__name__)

    def on_press(self, key):
        logger.debug("pressed %s", key)
        if not hasattr(key, "char"):
            return
        try:
            if key.char == "1":
                self.publish(
                    reason=HwButton("rotary_counter_clockwise"),
                    during_registration=False,
                )
            if key.char == "2":
                self.publish(
                    reason=HwButton("rotary_clockwise"), during_registration=False
                )
            if key.char == "3":
                self.publish(reason=HwButton("mode_button"), during_registration=False)
            if key.char == "4":
                self.publish(
                    reason=HwButton("invoke_button"), during_registration=False
                )
            if key.char == "5":
                brightness_examples = [0, 1, 3, 10, 10000]
                self.simulated_brightness = brightness_examples[
                    (brightness_examples.index(self.simulated_brightness) + 1)
                    % len(brightness_examples)
                ]
                logger.info("simulated brightness: %s", self.simulated_brightness)

        except Exception:
            logger.warning("%s", traceback.format_exc())

    def get_room_brightness(self) -> float:
        return self.simulated_brightness
