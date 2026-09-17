"""
Standalone digital logic-level probe using a spare Raspberry Pi GPIO pin.

Wire a jumper from the chosen BCM GPIO pin to whatever pad you want to
measure (e.g. the BS1/BS0 resistor pads on the OLED board). The pin is
alternately sampled with the internal pull-up and pull-down enabled:
- if the pad actively drives the line, both readings agree with the
  driven level (VCC or GND)
- if the pad is unconnected/floating, the reading just follows whichever
  internal resistor happens to be active, so the two samples disagree

Run this on the Pi directly, standalone (not while app_clock.py is running,
since it also drives GPIO). Avoid pins already used elsewhere in this repo:
SPI0 (8/9/10/11), display DC/RES (24/25), buttons/rotary (1/5/6/12/13).

Also initializes and turns on the SSD1322 OLED (same SPI wiring as
di_container.py: device=0, port=0, DC=GPIO24, RES=GPIO25) and fills it
white, so you can watch the panel while probing the BS pads.

Usage:
    python3 gpio_probe.py <bcm_pin> [--interval SECONDS] [--no-display]
"""

import argparse
import time

from RPi import GPIO
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1322


def read_state(pin: int) -> str:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(0.01)
    pulled_up = GPIO.input(pin)

    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    time.sleep(0.01)
    pulled_down = GPIO.input(pin)

    if pulled_up == GPIO.HIGH and pulled_down == GPIO.LOW:
        return "FLOATING"
    if pulled_up == GPIO.HIGH and pulled_down == GPIO.HIGH:
        return "VCC"
    if pulled_up == GPIO.LOW and pulled_down == GPIO.LOW:
        return "GND"
    return f"INDETERMINATE (pull-up={pulled_up}, pull-down={pulled_down})"


def turn_on_display():
    serial_interface = spi(device=0, port=0, bus_speed_hz=16000000)
    device = ssd1322(serial_interface=serial_interface)
    device.contrast(255)
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="white", fill="white")
    return device


def main():
    parser = argparse.ArgumentParser(
        description="Probe a signal's logic level via a spare GPIO pin (BCM numbering)"
    )
    parser.add_argument("pin", type=int, help="BCM GPIO number connected to the probe jumper")
    parser.add_argument(
        "--interval", type=float, default=0.5, help="Seconds between readings (default 0.5)"
    )
    parser.add_argument(
        "--no-display", action="store_true", help="Skip initializing/lighting up the OLED"
    )
    args = parser.parse_args()

    if not args.no_display:
        try:
            turn_on_display()
            print("Display initialized and filled white.")
        except Exception as e:
            print(f"Display init failed: {e}")

    GPIO.setmode(GPIO.BCM)
    try:
        print(
            f"Probing GPIO{args.pin} (BCM). Touch the jumper to a pad and watch "
            "the readout below. Ctrl+C to stop."
        )
        last = None
        while True:
            state = read_state(args.pin)
            if state != last:
                print(state)
                last = state
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup(args.pin)


if __name__ == "__main__":
    main()
