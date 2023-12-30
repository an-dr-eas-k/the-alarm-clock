import logging
import math
import time
import board
import adafruit_bh1750

def get_room_brightness() -> float:
	try:
		i2c = board.I2C()
		sensor = adafruit_bh1750.BH1750(i2c)
		logging.debug("raw sensor value in lux: %s", sensor.lux)
		return sensor.lux
	except:
		return 10000


if __name__ == "__main__":

	while True:
			print("%.2f Lux" % get_room_brightness())
			time.sleep(1)