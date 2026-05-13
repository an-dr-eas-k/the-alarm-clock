from concurrent.futures import ThreadPoolExecutor
import logging
from core.infrastructure.event_bus import EventBus
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwRotaryEvent,
    RotaryDirection,
)

logger = logging.getLogger("tac.core.infrastructure.rpi_gpio")

rotary_encoder_press_gpio: int = 5
rotary_encoder_a_gpio: int = 6
rotary_encoder_b_gpio: int = 13
mode_button_gpio: int = 12
invoke_button_gpio: int = 1


class RPiGPIOManager:

    executor: ThreadPoolExecutor
    gpio_callbacks = {}

    @property
    def _gpio_module(self):
        from RPi import GPIO  # type: ignore

        return GPIO

    def __init__(self, executor: ThreadPoolExecutor):
        self.executor = executor
        self.gpio_callbacks = {}

    def add_callback(self, pin_num, callback):
        self.gpio_callbacks[pin_num] = callback

    def setup(self):
        self._gpio_module.setmode(self._gpio_module.BCM)
        configured_pins = self.gpio_callbacks.keys()
        logger.info(f"Configuring gpio pins: {configured_pins}")

        for pin in configured_pins:
            self._gpio_module.setup(
                pin, self._gpio_module.IN, pull_up_down=self._gpio_module.PUD_UP
            )

            self._gpio_module.add_event_detect(
                pin,
                self._gpio_module.BOTH,
                callback=self.callback_wrapper,
                bouncetime=10,
            )

    def callback_wrapper(self, channel):
        all_pin_values = self.read_all_pins()
        logger.debug(
            f"GPIO event detected on channel {channel}, pin values: {all_pin_values}"
        )
        self.executor.submit(
            self.gpio_callbacks[channel],
            bool(all_pin_values[channel]),
            all_pin_values,
        )

    def read_all_pins(self):
        pin_values = {}
        for pin in self.gpio_callbacks.keys():
            pin_values[pin] = int(self._gpio_module.input(pin))
        return pin_values

    def cleanup(self):
        logger.info("Cleaning up GPIO")
        self._gpio_module.cleanup()


class GPIOInputManager:
    last_states = [(0, 0), (0, 0)]

    def __init__(self, gpio_manager: RPiGPIOManager, event_bus: EventBus = None):
        super().__init__()
        self.gpio_manager = gpio_manager
        self.event_bus = event_bus

        self.gpio_manager.add_callback(mode_button_gpio, self._mode_button_callback)
        self.gpio_manager.add_callback(invoke_button_gpio, self._invoke_button_callback)
        self.gpio_manager.add_callback(
            rotary_encoder_a_gpio, self._rotary_encoder_callback
        )
        self.gpio_manager.add_callback(rotary_encoder_b_gpio, lambda v, p: {})

        self.gpio_manager.setup()

        channel_a_value = int(
            not self.gpio_manager.read_all_pins()[rotary_encoder_a_gpio]
        )
        channel_b_value = int(
            not self.gpio_manager.read_all_pins()[rotary_encoder_b_gpio]
        )

        self.last_states = [(channel_a_value, channel_b_value), (None, None)]

        logger.info(
            f"gpio initialized for buttons and rotary encoder input. Initial rotary encoder state: {self.last_states[0]}"
        )

    def _rotary_encoder_callback(self, _: bool, pin_values=None):

        channel_a_value = pin_values[rotary_encoder_a_gpio]
        if channel_a_value == 0:
            return

        channel_b_value = pin_values[rotary_encoder_b_gpio]
        state = (channel_a_value, channel_b_value)
        logger.debug(
            f"Rotary encoder current state: {state}, last state: {self.last_states[0]}"
        )

        if channel_b_value != channel_a_value:
            logger.debug("Rotary clockwise detected")

            self.event_bus.emit(
                HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE)
            )
        else:
            logger.debug("Rotary counter-clockwise detected")
            self.event_bus.emit(
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE
                )
            )

        self.last_states[1] = self.last_states[0]
        self.last_states[0] = state

    def _mode_button_callback(self, pin_value: bool, _=None):
        logger.debug("Mode button state changed")
        self.event_bus.emit(
            HwButtonEvent(
                device_name=DeviceName.MODE_BUTTON,
                direction=ButtonDirection.DOWN if not pin_value else ButtonDirection.UP,
            )
        )

    def _invoke_button_callback(self, pin_value: bool, _=None):
        logger.debug("Invoke button state changed")
        self.event_bus.emit(
            HwButtonEvent(
                device_name=DeviceName.INVOKE_BUTTON,
                direction=ButtonDirection.DOWN if not pin_value else ButtonDirection.UP,
            )
        )
