import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
import evdev
from evdev import ecodes
from core.application.alarm_audio_service import AlarmAudioService
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.events_infrastructure import (
    DeviceName,
    HwButtonEvent,
    HwRotaryEvent,
    RotaryDirection,
)

logger = logging.getLogger("tac.core.infrastructure.keyboard_buttons")


class ComputerInfrastructure(IBrightnessSensor):
    simulated_brightness: float = 1.0

    def __init__(self, executor: ThreadPoolExecutor):
        self.log = logging.getLogger(self.__class__.__name__)
        self.executor = executor
        self.running = True
        self.executor.submit(self._run_loop)

    def _find_keyboards(self):
        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            return [d for d in devices if "keyboard" in d.name.lower()]
        except Exception as e:
            logger.error(f"Failed to list input devices: {e}")
        return []

    def _run_loop(self):
        devices = self._find_keyboards()
        if not devices:
            logger.error(
                "No keyboard device found for evdev. Ensure you have permissions to read /dev/input/event*"
            )
            return

        for device in devices:
            logger.info(f"Listening on {device.name} ({device.path})")
            self.executor.submit(self._listen_to_device, device)

    def _listen_to_device(self, device):
        try:
            for event in device.read_loop():
                if not self.running:
                    break
                if event.type == ecodes.EV_KEY and event.value == 1:  # 1 is key down
                    self.on_press(event, device)
        except Exception:
            logger.warning(
                "Error reading from device %s: %s", device.name, traceback.format_exc()
            )

    def configure(self, alarm_audio_service: AlarmAudioService):
        self.alarm_audio_service = alarm_audio_service
        self.config = alarm_audio_service.alarm_clock_context.config
        self.event_bus = alarm_audio_service.event_bus

    def on_press(self, event, device=None):
        key_code = event.code
        logger.debug(
            "on device %s pressed key code %s",
            device.name if device else "unknown",
            key_code,
        )

        try:
            if key_code == ecodes.KEY_1:
                self.event_bus.emit(
                    HwRotaryEvent(
                        DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE
                    )
                )
            elif key_code == ecodes.KEY_2:
                self.event_bus.emit(
                    HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE)
                )
            elif key_code == ecodes.KEY_3:
                self.event_bus.emit(HwButtonEvent(DeviceName.MODE_BUTTON))
            elif key_code == ecodes.KEY_4:
                self.event_bus.emit(HwButtonEvent(DeviceName.INVOKE_BUTTON))
            elif key_code == ecodes.KEY_5:
                brightness_examples = [0.0, 0.1, 0.3, 0.8, 1.0]
                self.simulated_brightness = brightness_examples[
                    (brightness_examples.index(self.simulated_brightness) + 1)
                    % len(brightness_examples)
                ]
                logger.info("simulated brightness: %s", self.simulated_brightness)
            elif key_code == ecodes.KEY_6:
                self.alarm_audio_service._ring_alarm(
                    self.config.get_default_alarm_definition()
                )
            elif key_code == ecodes.KEY_7:
                ad = self.config.get_default_alarm_definition()
                ad.audio_effect.audio_stream.stream_url = "invalid_stream_url"
                self.alarm_audio_service._ring_alarm(ad)

        except Exception:
            logger.warning("%s", traceback.format_exc())

    def get_room_brightness(self) -> float:
        return self.simulated_brightness

    def stop(self):
        self.running = False
