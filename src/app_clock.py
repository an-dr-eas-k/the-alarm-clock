"""
 - Add this line to /etc/rc.local (before the exit 0):
  -   /home/pi/ONBOOT.sh 2> /home/pi/ONBOOT.errors > /home/pi/ONBOOT.stdout &
  - Add the following ONBOOT.sh script to /home/pi and make it executable:
  
#!/bin/bash
cd /home/pi/iot-clock/src
python app_clock.py
"""

import datetime
import os
import time
import io
import base64
from io import BytesIO
from typing import Any
from tornado import httputil
import PIL.Image

import tornado.ioloop
import tornado.web
from tornado.web import Application

from disp_binary import BinaryDisplay
from disp_large7seg import Large7SegDisplay
from disp_place_holder import PlaceHolder
from disp_sat import SATDisplay
from disp_word import WordDisplay
from oled.oled_window import OLEDWindow
from oled.oled_stub import StubOLED


ON_HARDWARE = False

if ON_HARDWARE:
    from luma.oled.device import ssd1322,device
    import RPi.GPIO as GPIO
    from oled.oled_pi import OLED


# Singleton clock controller
CLOCK = None


class Clock:

    def __init__(self, window, displays, config):
        self._window = window
        self._displays = displays
        self._xofs = -1
        self._yofs = -1
        self._dirx = 1
        self._diry = 1
        self._config = config
        self.set_display(config['display_num'])

    def button_pressed_cb(self):
        self.set_display()

    def get_displays(self):
        return self._displays

    def get_config(self):
        return self._config

    def set_display(self, num=-1):
        if num >= 0:
            self._config['display_num'] = num
        else:
            self._config['display_num'] += 1
            if self._config['display_num'] >= len(self._displays):
                self._config['display_num'] = 0
        self._display = self._displays[self._config['display_num']][1]
        self.update_time()

    def update_time(self):
        window_size = self._display.get_window_size()
        limits = [256 - window_size[0], 64 - window_size[1]]

        self._xofs += self._dirx
        if self._xofs > limits[0]:
            self._xofs = limits[0]
            self._dirx = -1
        if self._xofs < 0:
            self._xofs = 0
            self._dirx = 1

        self._yofs += self._diry
        if self._yofs > limits[1]:
            self._yofs = limits[1]
            self._diry = -1
        if self._yofs < 0:
            self._yofs = 0
            self._diry = 1

        now = datetime.datetime.now()

        hours = now.hour
        mins = now.minute
        secs = now.second

        self._window.clear()
        self._display.make_time(self._xofs, self._yofs, hours, mins, secs, self._config)
        self._window.draw_screen_buffer()


class DisplayHandler(tornado.web.RequestHandler):
    oledStub:StubOLED

    def initialize(self, oledStub: StubOLED) -> None:
        self.oledStub = oledStub

    def get(self):
        buffered = io.BytesIO()
        img= self.oledStub.getImage()
        img.save(buffered, format="png")
        img.seek(0)
        img_str = base64.b64encode(buffered.getvalue())
        my_html = '<img width="800" src="data:image/png;base64, {}">'.format(img_str.decode('utf-8'))
        self.write(my_html)

class ClockHandler(tornado.web.RequestHandler):

    def _get_json(self):
        config = CLOCK.get_config()
        disps = []
        for item in CLOCK.get_displays():
            disps.append(item[0])
        ret = {
            'displays': disps,
            'display_num': config['display_num'],
            'brightness': config['brightness'],
            'am_pm': config['am_pm'],
        }        
        return ret

    def get(self):

        # display_num : 0-N
        # brightness : 0-15
        # am_pm : true/false

        display_num = self.get_argument('display_num', None)
        brightness = self.get_argument('brightness', None)
        am_pm = self.get_argument('am_pm', None)

        changes = False

        if display_num is not None:
            config['display_num'] = int(display_num)
            changes = True

        if brightness is not None:
            config['brightness'] = int(brightness)
            changes = True

        if am_pm is not None:
            if am_pm.upper().startswith('T'):
                config['am_pm'] = True
            else:
                config['am_pm'] = False
            changes = True

        if changes:
            loop.add_callback(CLOCK.set_display, config['display_num'])

        self.set_header('Content-Type', 'application/json')
        self.write(self._get_json())


if __name__ == '__main__':

    # The OLED hardware driver
    if ON_HARDWARE:
        oled = OLED()
    else:
        oled = StubOLED()
    window = OLEDWindow(oled, 0, 0, 256, 64)

    displays = [
        ('7 Segment', Large7SegDisplay(window)),                 
        ('Binary', BinaryDisplay(window)),        
        ('Word', WordDisplay(window)),       
        ('S&T', SATDisplay(window)),
        ('Analog', PlaceHolder(window, 'Analog')),
        ('Roman', PlaceHolder(window, 'Roman')),
        ('Tetris', PlaceHolder(window, 'Tetris')),
        #('Text', PlaceHolder(window, 'Text')),
    ]

    # TODO: this should persist in a config file
    config = {
        'brightness': 15,
        'am_pm': True,
        'display_num': 0
    }

    CLOCK = Clock(window, displays, config)

    loop = tornado.ioloop.IOLoop.current()

    # Make sure the button handler runs in the tornando I/O loop
    def _button_handler(_channel):
        loop.add_callback(CLOCK.button_pressed_cb)

    if ON_HARDWARE:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(23, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(23, GPIO.FALLING, callback=_button_handler, bouncetime=500)

    root = os.path.join(os.path.dirname(__file__), "webroot")
    handlers = [
        (r"/clock", ClockHandler ),
        (r"/display", DisplayHandler, {"oledStub": oled} ),
        (r"/(.*)", tornado.web.StaticFileHandler, {"path": root, "default_filename": "index.html"}),
    ]

    app = tornado.web.Application(handlers)
    if ON_HARDWARE:
        app.listen(80)
    else:
        app.listen(8080)

    # Every 10 seconds, update the display
    def _time_change():
        CLOCK.update_time()
        loop.call_later(10, _time_change)
    _time_change()

    loop.start()
