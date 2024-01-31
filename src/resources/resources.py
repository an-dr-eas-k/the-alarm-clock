import logging.config
import os


resources_dir = os.path.dirname(os.path.realpath(__file__))
media_dir = os.path.join(resources_dir, "media")

fonts_dir = f"{media_dir}/fonts"
icons_dir = f"{media_dir}/icons"
weather_icons_dir = f"{icons_dir}/weather"
sounds_dir = f"{media_dir}/sounds"
alarms_dir = f"{sounds_dir}/alarms"

def init_logging():
	logging.config.fileConfig(os.path.join(resources_dir, 'logging.conf'))