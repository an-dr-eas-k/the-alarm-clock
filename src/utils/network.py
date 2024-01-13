
import subprocess


def is_ping_successful(hostname):
	result = subprocess.run(
		["ping", "-c", "1", hostname], 
		stdout=subprocess.DEVNULL, 
		stderr=subprocess.DEVNULL)
	return result.returncode == 0

def is_internet_available():
	return is_ping_successful("google.com")