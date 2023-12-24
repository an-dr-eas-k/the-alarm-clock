import logging
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

def get_room_brightness_255() -> int:
	return int(max(0, min(255, get_room_brightness_255()/2500 * 255)))


if __name__ == "__main__":

	while True:
			print("%.2f Lux" % get_room_brightness())
			time.sleep(1)