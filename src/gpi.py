import logging
import math
import time
import board
import adafruit_bh1750

def get_room_brightness() -> float:
	try:
		i2c = board.I2C()
		sensor = adafruit_bh1750.BH1750(i2c)
		logging.info("brightness: %s", sensor.lux)
		return sensor.lux
	except:
		return -1

def get_room_brightness_16() -> int:
	return int(max(0, min(15, get_room_brightness()/2500 * 15)))

def get_room_brightness_16_v2() -> int:
	return 15 if get_room_brightness() > 1 else 1
	# return int(max(0, min(255, 500/(1+math.exp(-0.1*get_room_brightness()))-250)))


if __name__ == "__main__":

	while True:
			print("%.2f Lux" % get_room_brightness())
			time.sleep(1)