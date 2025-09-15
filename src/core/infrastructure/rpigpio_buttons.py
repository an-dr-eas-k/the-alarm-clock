import logging
import RPi.GPIO as GPIO
import threading
import time

logger = logging.getLogger("tac.gpio_buttons")


class RpiGpioButtonManager:
    def __init__(self, button_configs):
        """
        button_configs: list of dicts, each dict should have:
            - 'pin': GPIO pin number
            - 'when_activated': callback for activation (optional)
            - 'when_held': callback for hold (optional)
            - 'hold_time': hold time in seconds (optional)
        """
        self.button_configs = button_configs
        self._stop_event = threading.Event()
        self._threads = []
        GPIO.setmode(GPIO.BCM)
        for cfg in button_configs:
            pin = cfg["pin"]
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            if "when_activated" in cfg:
                GPIO.add_event_detect(
                    pin,
                    GPIO.FALLING,
                    callback=lambda ch, cb=cfg["when_activated"]: cb(),
                    bouncetime=200,
                )
            if "when_held" in cfg and "hold_time" in cfg:
                t = threading.Thread(
                    target=self._hold_monitor,
                    args=(pin, cfg["hold_time"], cfg["when_held"]),
                )
                t.daemon = True
                t.start()
                self._threads.append(t)
        logger.info("GPIO mode: %s", GPIO.getmode())

    def _hold_monitor(self, pin, hold_time, callback):
        while not self._stop_event.is_set():
            if GPIO.input(pin) == GPIO.LOW:
                start = time.time()
                while GPIO.input(pin) == GPIO.LOW and not self._stop_event.is_set():
                    time.sleep(0.01)
                duration = time.time() - start
                if duration >= hold_time:
                    callback()
            time.sleep(0.05)

    def close(self):
        self._stop_event.set()
        time.sleep(0.1)
        GPIO.cleanup()
