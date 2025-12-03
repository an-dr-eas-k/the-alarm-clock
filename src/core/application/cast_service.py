import logging
import subprocess
import threading
import os
from core.infrastructure.event_bus import EventBus

logger = logging.getLogger("tac.cast_service")


class CastService:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.process = None
        # Path relative to the project root
        self.executable_path = os.path.abspath(
            "vendor/openscreen/out/Default/cast_receiver"
        )
        # Default to wlan0, but should ideally be configurable or auto-detected
        self.interface = "wlan0"

    def start_cast_receiver(self):
        if not os.path.exists(self.executable_path):
            logger.warning(
                f"Cast receiver executable not found at {self.executable_path}. Casting will not work. Please build Open Screen."
            )
            return

        if self.process and self.process.poll() is None:
            logger.info("Cast receiver is already running.")
            return

        try:
            # Arguments for cast_receiver:
            # -d: Use a generated developer certificate (self-signed).
            # <interface>: The network interface to bind to.
            cmd = [self.executable_path, "-d", self.interface]
            logger.info(f"Starting cast receiver: {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

            # Start a thread to read output so buffer doesn't fill up
            threading.Thread(target=self._monitor_output, daemon=True).start()

        except Exception as e:
            logger.error(f"Failed to start cast receiver: {e}")

    def stop_cast_receiver(self):
        if self.process and self.process.poll() is None:
            logger.info("Stopping cast receiver...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _monitor_output(self):
        if not self.process:
            return

        try:
            for line in self.process.stdout:
                logger.debug(f"[CastReceiver] {line.strip()}")
        except Exception as e:
            logger.error(f"Error reading cast receiver output: {e}")

        logger.info("Cast receiver process exited.")
