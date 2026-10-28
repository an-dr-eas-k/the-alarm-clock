import json
import os
import sys
import unittest
from unittest import mock

import app_librespotify_event_listener as listener_module
from app_librespotify_event_listener import LibreSpotifyEventListenerApp
from resources import resources


def build_app(*argv):
    with mock.patch.object(sys, "argv", ["listener", *argv]):
        return LibreSpotifyEventListenerApp()


class ArgumentParsingTest(unittest.TestCase):
    def test_software_flag_defaults_to_false(self):
        self.assertFalse(build_app().args.software)

    def test_short_software_flag(self):
        self.assertTrue(build_app("-s").args.software)

    def test_long_software_flag(self):
        self.assertTrue(build_app("--software").args.software)

    def test_unknown_argument_exits(self):
        with mock.patch.object(sys, "stderr"), self.assertRaises(SystemExit):
            build_app("--bogus")


class PostSpotifyDataTest(unittest.TestCase):
    def test_posts_json_payload_to_api_route(self):
        app = build_app()
        with mock.patch.object(listener_module, "json_api", return_value={"ok": 1}) as api:
            result = app.post_spotify_data({"player_event": "playing"})

        self.assertTrue(result)
        url, headers, data = api.call_args.args
        self.assertEqual(url, "https://localhost:443/api/librespotify")
        self.assertEqual(headers, {"Content-Type": "application/json"})
        self.assertEqual(json.loads(data.decode("utf-8")), {"player_event": "playing"})

    def test_returns_false_when_api_call_fails(self):
        app = build_app()
        with mock.patch.object(listener_module, "json_api", return_value=False):
            self.assertIs(app.post_spotify_data({}), False)

    def test_url_is_built_from_instance_settings(self):
        app = build_app()
        app.alarm_clock_protocol, app.alarm_clock_port = "http", 8080
        app.alarm_clock_route = "//api/x/"
        with mock.patch.object(listener_module, "json_api", return_value=True) as api:
            app.post_spotify_data({})
        self.assertEqual(api.call_args.args[0], "http://localhost:8080/api/x")

    def test_non_ascii_payload_is_utf8_encoded(self):
        app = build_app()
        with mock.patch.object(listener_module, "json_api", return_value=True) as api:
            app.post_spotify_data({"name": "Björk – Jóga"})
        data = api.call_args.args[2]
        self.assertEqual(json.loads(data.decode("utf-8"))["name"], "Björk – Jóga")


class GetEnvironmentVariablesTest(unittest.TestCase):
    def test_returns_copy_of_process_environment(self):
        app = build_app()
        with mock.patch.dict("os.environ", {"PLAYER_EVENT": "paused"}):
            env = app.get_environment_variables()
            env["PLAYER_EVENT"] = "changed"
            self.assertEqual(os.environ["PLAYER_EVENT"], "paused")


class GoTest(unittest.TestCase):
    def run_go(self, env, *argv, post_result=True):
        app = build_app(*argv)
        with mock.patch.object(app, "get_environment_variables", return_value=env), \
                mock.patch.object(app, "post_spotify_data", return_value=post_result) as post, \
                self.assertLogs("tac.librespot_ev", "INFO"):
            app.go()
        return app, post

    def test_only_librespot_variables_are_forwarded_with_lowercase_keys(self):
        env = {
            "PLAYER_EVENT": "playing",
            "TRACK_ID": "abc",
            "PATH": "/usr/bin",
            "HOME": "/root",
            "Name": "wrong-case-is-ignored",
        }
        _, post = self.run_go(env)
        post.assert_called_once_with({"player_event": "playing", "track_id": "abc"})

    def test_every_known_variable_is_translated(self):
        env = {name: "v" for name in resources.librespotify_env_vars}
        _, post = self.run_go(env)
        self.assertEqual(
            set(post.call_args.args[0]),
            {name.lower() for name in resources.librespotify_env_vars},
        )

    def test_no_relevant_variables_posts_empty_payload(self):
        _, post = self.run_go({"PATH": "/bin"})
        post.assert_called_once_with({})

    def test_production_mode_keeps_https_endpoint(self):
        app, _ = self.run_go({})
        self.assertEqual((app.alarm_clock_protocol, app.alarm_clock_port), ("https", 443))

    def test_software_mode_switches_to_plain_http_on_8080(self):
        app, _ = self.run_go({}, "-s")
        self.assertEqual((app.alarm_clock_protocol, app.alarm_clock_port), ("http", 8080))

    def test_software_mode_does_not_change_class_defaults(self):
        self.run_go({}, "-s")
        self.assertEqual(LibreSpotifyEventListenerApp.alarm_clock_protocol, "https")
        self.assertEqual(LibreSpotifyEventListenerApp.alarm_clock_port, 443)

    def test_failed_post_exits_with_status_one(self):
        app = build_app()
        with mock.patch.object(app, "get_environment_variables", return_value={}), \
                mock.patch.object(app, "post_spotify_data", return_value=False), \
                self.assertLogs("tac.librespot_ev", "WARNING"):
            with self.assertRaises(SystemExit) as ctx:
                app.go()
        self.assertEqual(ctx.exception.code, 1)

    def test_successful_post_does_not_exit(self):
        self.run_go({"PLAYER_EVENT": "stopped"})


class ModuleImportTest(unittest.TestCase):
    def test_importing_module_does_not_run_the_app(self):
        self.assertTrue(hasattr(listener_module, "LibreSpotifyEventListenerApp"))
        self.assertEqual(LibreSpotifyEventListenerApp.alarm_clock_route, "/api/librespotify")


if __name__ == "__main__":
    unittest.main()
