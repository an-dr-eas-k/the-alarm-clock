import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

import tornado.escape
import tornado.ioloop
import tornado.web

from core.application.calendar_service import CalendarService
from core.infrastructure.google_auth import GoogleAuthError

logger = logging.getLogger("tac.core.interface.web.auth")


class CurrentUserMixin:
    """Shared `get_current_user` implementation for handlers that need to know
    whether the current browser session belongs to a logged-in (and allowed)
    Google user. Session identity is a signed cookie set after a successful
    Google device-flow login - no server-side session storage is needed.
    """

    def get_current_user(self):
        user = self.get_secure_cookie("tac_user")
        return user.decode("utf-8") if user else None

    def get_current_user_picture(self):
        picture = self.get_secure_cookie("tac_user_picture")
        return picture.decode("utf-8") if picture else None


class GoogleLoginStartHandler(CurrentUserMixin, tornado.web.RequestHandler):
    """Starts a Google OAuth device-flow login: returns a short user code and
    verification URL the user opens on any other device (phone/laptop) to
    grant access - no reachable redirect URI/hostname is required."""

    def initialize(
        self, calendar_service: CalendarService, executor: ThreadPoolExecutor
    ) -> None:
        self.calendar_service = calendar_service
        self.executor = executor

    async def post(self):
        try:
            result = await tornado.ioloop.IOLoop.current().run_in_executor(
                self.executor, self.calendar_service.start_device_login
            )
            self.set_header("Content-Type", "application/json")
            self.write(result)
        except GoogleAuthError as e:
            self.set_status(400)
            self.write({"status": "error", "message": str(e)})
        except Exception:
            logger.warning("%s", traceback.format_exc())
            self.set_status(500)
            self.write({"status": "error", "message": "internal error"})


class GoogleLoginPollHandler(CurrentUserMixin, tornado.web.RequestHandler):
    """Polled by the login page while the user completes the Google login."""

    def initialize(
        self, calendar_service: CalendarService, executor: ThreadPoolExecutor
    ) -> None:
        self.calendar_service = calendar_service
        self.executor = executor

    async def get(self):
        try:
            device_code = self.get_argument("device_code")
            result = await tornado.ioloop.IOLoop.current().run_in_executor(
                self.executor,
                self.calendar_service.poll_device_login,
                device_code,
            )
            if result.get("status") == "complete":
                self.set_secure_cookie("tac_user", result["email"], expires_days=30)
                if result.get("picture"):
                    self.set_secure_cookie(
                        "tac_user_picture", result["picture"], expires_days=30
                    )
            self.set_header("Content-Type", "application/json")
            self.write(result)
        except Exception:
            logger.warning("%s", traceback.format_exc())
            self.set_status(500)
            self.write({"status": "error", "message": "internal error"})


class LogoutHandler(CurrentUserMixin, tornado.web.RequestHandler):

    def initialize(
        self, calendar_service: CalendarService, executor: ThreadPoolExecutor
    ) -> None:
        self.calendar_service = calendar_service
        self.executor = executor

    async def post(self):
        user = self.current_user
        if user:
            await tornado.ioloop.IOLoop.current().run_in_executor(
                self.executor, self.calendar_service.logout, user
            )
        self.clear_cookie("tac_user")
        self.clear_cookie("tac_user_picture")
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok"})
