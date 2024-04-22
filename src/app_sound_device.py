
import argparse
import logging

from resources.resources import init_logging
from utils.sound_device import SoundDevice

logger = logging.getLogger("tac.app_sound_device")

if __name__ == "__main__":
	init_logging()
	parser = argparse.ArgumentParser("SoundDevice")
	parser.add_argument("-D", '--device', type=str, default="default")
	args = parser.parse_args()
	sd = SoundDevice(args.device)
	logger.info("volume: %s", sd.get_system_volume()) 