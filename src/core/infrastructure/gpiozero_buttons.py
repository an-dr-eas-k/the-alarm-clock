import logging
from gpiozero import Button, Device

logger = logging.getLogger("tac.gpio_buttons")


class GpioZeroButtonManager:
    def __init__(self, button_configs):
        """
        button_configs: list of dicts, each dict should have:
            - 'pin': GPIO pin number
            - 'when_activated': callback for activation (optional)
            - 'when_held': callback for hold (optional)
            - 'hold_time': hold time in seconds (optional)
        """
        self.buttons = []
        for cfg in button_configs:
            b = Button(pin=cfg["pin"], bounce_time=0.2)
            if "hold_time" in cfg:
                b.hold_time = cfg["hold_time"]
                b.hold_repeat = True
            if "when_held" in cfg:
                b.when_held = cfg["when_held"]
            if "when_activated" in cfg:
                b.when_activated = cfg["when_activated"]
            self.buttons.append(b)
        logger.info("pin factory: %s", Device.pin_factory)

    def close(self):
        for b in self.buttons:
            b.close()
