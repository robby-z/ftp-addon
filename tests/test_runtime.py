from __future__ import annotations

import importlib.machinery
import importlib.util
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "reolink_ftps/rootfs/usr/local/bin/reolink-ftps"
loader = importlib.machinery.SourceFileLoader("reolink_runtime", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
runtime = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = runtime
loader.exec_module(runtime)


def options() -> dict:
    return {
        "storage": {
            "root": "media", "directory": "ReolinkSSD/reolink", "minimum_free_space_gb": 1,
            "stop_uploads_below_free_space": True, "require_marker_file": False,
            "initialize_marker_file": False, "marker_file": ".reolink-storage",
        },
        "users": [
            {"username": "camera_front", "password": "front-secret", "directory": "front", "read_only": False},
            {"username": "viewer", "password": "viewer-secret", "directory": "front", "read_only": True},
        ],
        "tls": {"require_tls": True, "allow_plain_ftp": False, "certificate": "", "private_key": ""},
        "pasv_address": "127.0.0.1", "max_clients": 20, "max_per_ip": 5,
        "idle_session_timeout": 600, "data_connection_timeout": 300, "delay_failed_login": 2,
        "retention_days": 0, "log_level": "info",
    }


def chunked_json_request(
    base: str, path: str, payload: dict, *, token: str, content_length: bool = False,
):
    parsed = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    body = json.dumps(payload).encode()
    connection.putrequest("POST", path)
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Transfer-Encoding", "chunked")
    connection.putheader("X-Reolink-CSRF", token)
    if content_length:
        connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()
    connection.send(f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n")
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "media"
        self.share = self.root / "share"
        self.data = self.root / "data"
        self.ssl = self.root / "ssl"
        for path in (self.media, self.share, self.data, self.ssl):
            path.mkdir()
        (self.media / "ReolinkSSD").mkdir()
        self.roots = {"media": self.media, "share": self.share}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, value=None):
        return runtime.prepare_runtime(value or options(), data_dir=self.data, ssl_dir=self.ssl, mapped_roots=self.roots)

    def test_valid_config_creates_recording_and_user_directories(self):
        config = self.prepare()
        self.assertEqual(config.recording_root, (self.media / "ReolinkSSD/reolink").resolve())
        self.assertTrue((config.recording_root / "front").is_dir())
        self.assertEqual(len(config.users), 2)

    def test_invalid_usernames_and_shell_metacharacters(self):
        for username in ("", "root", "anonymous", "-option", ".hidden", "bad;name", "$(bad)", "line\nbreak", "x" * 33):
            value = options()
            value["users"][0]["username"] = username
            with self.subTest(username=username), self.assertRaises(runtime.ConfigError):
                self.prepare(value)

    def test_duplicate_user_rejected(self):
        value = options()
        value["users"][1]["username"] = "camera_front"
        with self.assertRaisesRegex(runtime.ConfigError, "Duplicate"):
            self.prepare(value)

    def test_empty_password_and_empty_users_rejected(self):
        value = options()
        value["users"][0]["password"] = ""
        with self.assertRaises(runtime.ConfigError):
            self.prepare(value)
        value = options()
        value["users"] = []
        with self.assertRaises(runtime.ConfigError):
            self.prepare(value)

    def test_missing_read_only_defaults_to_write_access(self):
        value = options()
        del value["users"][0]["read_only"]
        config = self.prepare(value)
        self.assertFalse(config.users[0].read_only)

        value = options()
        value["users"][0]["read_only"] = "false"
        with self.assertRaisesRegex(runtime.ConfigError, "read_only"):
            self.prepare(value)

    def test_absolute_traversal_and_path_tricks_rejected(self):
        for directory in ("/media/ReolinkSSD/reolink", "../reolink", "ReolinkSSD/../share", "ReolinkSSD\\reolink", "ReolinkSSD/reo link", "ReolinkSSD/./reolink"):
            value = options()
            value["storage"]["directory"] = directory
            with self.subTest(directory=directory), self.assertRaises(runtime.ConfigError):
                self.prepare(value)

    def test_storage_directory_requires_anchor_and_child(self):
        value = options()
        value["storage"]["directory"] = "ReolinkSSD"
        with self.assertRaises(runtime.ConfigError):
            self.prepare(value)

    def test_missing_anchor_is_not_created(self):
        (self.media / "ReolinkSSD").rmdir()
        with self.assertRaisesRegex(runtime.ConfigError, "Refusing to start"):
            self.prepare()
        self.assertFalse((self.media / "ReolinkSSD").exists())

    def test_storage_symlink_escape_rejected(self):
        (self.media / "ReolinkSSD").rmdir()
        (self.media / "ReolinkSSD").symlink_to(self.share, target_is_directory=True)
        with self.assertRaises(runtime.ConfigError):
            self.prepare()

    def test_user_directory_symlink_rejected(self):
        recording = self.media / "ReolinkSSD/reolink"
        recording.mkdir()
        (recording / "front").symlink_to(self.share, target_is_directory=True)
        with self.assertRaises(runtime.ConfigError):
            self.prepare()

    def test_marker_initialization_and_requirement(self):
        value = options()
        value["storage"]["initialize_marker_file"] = True
        value["storage"]["require_marker_file"] = True
        self.prepare(value)
        self.assertTrue((self.media / "ReolinkSSD/.reolink-storage").is_file())
        (self.media / "ReolinkSSD/.reolink-storage").unlink()
        value["storage"]["initialize_marker_file"] = False
        with self.assertRaisesRegex(runtime.ConfigError, "marker"):
            self.prepare(value)

    def test_self_signed_certificate_generated_and_reused(self):
        first = self.prepare()
        certificate_bytes = first.cert.read_bytes()
        key_bytes = first.key.read_bytes()
        second = self.prepare()
        self.assertEqual(certificate_bytes, second.cert.read_bytes())
        self.assertEqual(key_bytes, second.key.read_bytes())
        self.assertEqual(first.cert_source, "persistent self-signed certificate")

    def test_home_assistant_certificate_mismatch_rejected(self):
        first = self.prepare()
        (self.ssl / "cert.pem").write_bytes(first.cert.read_bytes())
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(self.ssl / "wrong.key")],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        value = options()
        value["tls"]["certificate"] = "cert.pem"
        value["tls"]["private_key"] = "wrong.key"
        with self.assertRaisesRegex(runtime.ConfigError, "do not match"):
            self.prepare(value)

    def test_matching_home_assistant_certificate_is_accepted(self):
        first = self.prepare()
        (self.ssl / "cert.pem").write_bytes(first.cert.read_bytes())
        (self.ssl / "key.pem").write_bytes(first.key.read_bytes())
        value = options()
        value["tls"]["certificate"] = "cert.pem"
        value["tls"]["private_key"] = "key.pem"
        config = self.prepare(value)
        self.assertEqual(config.cert_source, "Home Assistant /ssl certificate")

    def test_missing_certificate_and_persistent_tls_symlink_rejected(self):
        value = options()
        value["tls"]["certificate"] = "missing.pem"
        value["tls"]["private_key"] = "missing.key"
        with self.assertRaisesRegex(runtime.ConfigError, "does not exist"):
            self.prepare(value)
        (self.data / "tls").symlink_to(self.share, target_is_directory=True)
        with self.assertRaisesRegex(runtime.ConfigError, "symbolic link"):
            self.prepare()

    def test_generated_vsftpd_configuration_and_read_only_override(self):
        config = self.prepare()
        run_dir = self.root / "run"
        user_dir = self.root / "user-config"
        path = runtime.build_vsftpd_config(config, run_dir, user_dir)
        text = path.read_text()
        self.assertIn("force_local_logins_ssl=YES", text)
        self.assertIn("seccomp_sandbox=NO", text)
        self.assertIn("isolate_network=NO", text)
        self.assertIn("pam_service_name=reolink-ftps", text)
        self.assertIn("ssl_tlsv1=YES", text)
        self.assertIn("secure_chroot_dir=/run/vsftpd/empty", text)
        self.assertIn("pasv_min_port=30000", text)
        self.assertIn("pasv_max_port=30019", text)
        self.assertIn("pasv_address=127.0.0.1", text)
        self.assertEqual((user_dir / "camera_front").read_text().splitlines()[-1], "write_enable=YES")
        self.assertEqual((user_dir / "viewer").read_text().splitlines()[-1], "write_enable=NO")

    def test_browser_paths_ranges_and_symlink_safety(self):
        config = self.prepare()
        user_root = config.recording_root / "front"
        nested = user_root / "2026" / "08"
        nested.mkdir(parents=True)
        recording = nested / "clip.mp4"
        recording.write_bytes(b"0123456789")
        outside = self.share / "outside.mp4"
        outside.write_bytes(b"outside")
        (user_root / "escape.mp4").symlink_to(outside)

        entries = runtime.list_browser_directory(user_root, "")
        self.assertEqual([entry["name"] for entry in entries], ["2026"])
        self.assertEqual(runtime.resolve_browser_path(user_root, "2026/08/clip.mp4"), recording)
        for unsafe in ("../outside.mp4", "/etc/passwd", "2026/../outside", "escape.mp4"):
            with self.subTest(path=unsafe), self.assertRaises(runtime.BrowserRequestError):
                runtime.resolve_browser_path(user_root, unsafe)
        self.assertEqual(runtime.parse_byte_range("bytes=2-5", 10), (2, 5, True))
        self.assertEqual(runtime.parse_byte_range("bytes=-3", 10), (7, 9, True))
        self.assertEqual(runtime.parse_byte_range(None, 10), (0, 9, False))
        for invalid in ("items=0-1", "bytes=10-11", "bytes=4-2", "bytes=0-1,4-5"):
            with self.subTest(value=invalid), self.assertRaises(runtime.BrowserRequestError):
                runtime.parse_byte_range(invalid, 10)

    def test_ingress_browser_users_listing_streaming_and_access_control(self):
        config = self.prepare()
        recording = config.recording_root / "front/clip.mp4"
        recording.write_bytes(b"0123456789")
        index = self.root / "index.html"
        index.write_text("<script>const base=__INGRESS_PATH__;</script>")
        browser = runtime.RecordingBrowser(
            config, host="127.0.0.1", port=0, allowed_clients={"127.0.0.1"}, index_path=index,
            data_dir=self.data,
        )
        browser.start()
        base = f"http://127.0.0.1:{browser.port}"
        try:
            with urllib.request.urlopen(f"{base}/api/users") as response:
                users = json.load(response)["users"]
            self.assertEqual([user["username"] for user in users], ["camera_front", "viewer"])
            self.assertNotIn("password", users[0])

            query = urllib.parse.urlencode({"user": "camera_front", "path": ""})
            with urllib.request.urlopen(f"{base}/api/list?{query}") as response:
                listing = json.load(response)
            self.assertEqual(listing["entries"][0]["name"], "clip.mp4")

            query = urllib.parse.urlencode({"user": "camera_front", "path": "clip.mp4"})
            request = urllib.request.Request(f"{base}/media?{query}", headers={"Range": "bytes=2-5"})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
                self.assertEqual(response.read(), b"2345")

            request = urllib.request.Request(f"{base}/media?{query}", headers={"Range": "bytes=99-"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code, 416)
            self.assertEqual(caught.exception.headers["Content-Range"], "bytes */10")
            caught.exception.close()

            request = urllib.request.Request(f"{base}/", headers={"X-Ingress-Path": "/api/hassio_ingress/test"})
            with urllib.request.urlopen(request) as response:
                self.assertIn(b'"/api/hassio_ingress/test"', response.read())

            traversal = urllib.parse.urlencode({"user": "camera_front", "path": "../outside"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"{base}/api/list?{traversal}")
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        finally:
            browser.stop()

        denied = runtime.RecordingBrowser(
            config, host="127.0.0.1", port=0, allowed_clients={"192.0.2.1"}, index_path=index,
            data_dir=self.data,
        )
        denied.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{denied.port}/api/users")
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        finally:
            denied.stop()

    def test_recording_index_filters_sorts_paginates_and_persists(self):
        config = self.prepare()
        camera_root = config.recording_root / "front"
        clips = [
            ("2026/08/older.mp4", b"old", 300),
            ("2026/08/newer.MKV", b"newer", 100),
            ("other/newest.mp4", b"newest!", 50),
        ]
        now = time.time()
        for relative, content, age in clips:
            path = camera_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            os.utime(path, (now - age, now - age))
        (camera_root / "ignored.txt").write_text("not a video")
        fresh = camera_root / "active.mp4"
        fresh.write_bytes(b"active upload")
        outside = self.share / "outside.mp4"
        outside.write_bytes(b"outside")
        (camera_root / "linked.mp4").symlink_to(outside)

        sources = runtime.browser_camera_roots(config)
        self.assertEqual(sources, {"camera_front": camera_root.resolve()})
        database = self.data / "recordings-index.sqlite3"
        index = runtime.RecordingIndex(database, sources)
        index._scan_all()

        result = index.query(page_size=2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["pages"], 2)
        self.assertEqual([item["name"] for item in result["items"]], ["newest.mp4", "newer.MKV"])
        self.assertEqual(index.query(search="older")["total"], 1)
        self.assertEqual(index.query(sort="size", direction="asc")["items"][0]["name"], "older.mp4")
        self.assertEqual(index.query(from_time=int(now - 150))["total"], 2)
        self.assertEqual(index.query(to_time=int(now - 150))["total"], 1)
        self.assertEqual(index.query()["filtered_size"], sum(len(content) for _, content, _ in clips))
        self.assertFalse(index.indexed("camera_front", "active.mp4"))
        self.assertFalse(index.indexed("camera_front", "linked.mp4"))

        index.set_watched("camera_front", "2026/08/newer.MKV", True)
        self.assertEqual(index.query(watched="watched")["total"], 1)
        self.assertEqual(index.query(watched="unwatched")["total"], 2)
        index._scan_all()
        self.assertTrue(index.query(search="newer")["items"][0]["watched"])

        reopened = runtime.RecordingIndex(database, sources)
        self.assertEqual(reopened.query()["total"], 3)
        self.assertTrue(reopened.query(search="newer")["items"][0]["watched"])

        changed = camera_root / "2026/08/newer.MKV"
        changed.write_bytes(b"replacement with a different identity")
        os.utime(changed, (now - 45, now - 45))
        reopened._scan_all()
        self.assertFalse(reopened.query(search="newer")["items"][0]["watched"])

    def test_recording_index_migrates_v1_watched_schema(self):
        config = self.prepare()
        database = self.data / "recordings-index.sqlite3"
        with runtime.closing(runtime.sqlite3.connect(database)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE recordings (
                    camera TEXT NOT NULL, relative_path TEXT NOT NULL, name TEXT NOT NULL,
                    directory TEXT NOT NULL, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
                    modified INTEGER NOT NULL, mime TEXT NOT NULL, seen_scan INTEGER NOT NULL,
                    PRIMARY KEY (camera, relative_path)
                )
                """
            )
            connection.execute(
                "INSERT INTO recordings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("camera_front", "legacy.mp4", "legacy.mp4", ".", 12, 123, 100, "video/mp4", 1),
            )
            connection.execute("PRAGMA user_version = 1")
        index = runtime.RecordingIndex(database, runtime.browser_camera_roots(config))
        item = index.query()["items"][0]
        self.assertFalse(item["watched"])
        index.set_watched("camera_front", "legacy.mp4", True)
        self.assertTrue(index.query()["items"][0]["watched"])
        with runtime.closing(runtime.sqlite3.connect(database)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_recording_index_rebuilds_corrupt_database(self):
        config = self.prepare()
        database = self.data / "recordings-index.sqlite3"
        database.write_bytes(b"not sqlite")
        index = runtime.RecordingIndex(database, runtime.browser_camera_roots(config))
        self.assertEqual(index.query()["total"], 0)

    def test_recording_delete_requires_csrf_index_and_stable_video(self):
        config = self.prepare()
        root = config.recording_root / "front"
        recording = root / "day/clip.mp4"
        recording.parent.mkdir()
        recording.write_bytes(b"0123456789")
        active = root / "day/active.mp4"
        active.write_bytes(b"finished first")
        replaced = root / "day/replaced.mp4"
        replaced.write_bytes(b"inside")
        old = time.time() - 60
        for path in (recording, active, replaced):
            os.utime(path, (old, old))
        index_html = self.root / "index.html"
        index_html.write_text("test")
        browser = runtime.RecordingBrowser(
            config, host="127.0.0.1", port=0, allowed_clients={"127.0.0.1"},
            index_path=index_html, data_dir=self.data, scan_interval=3600,
        )
        browser.index._scan_all()
        active.write_bytes(b"upload resumed")
        replaced.unlink()
        outside = self.share / "outside.mp4"
        outside.write_bytes(b"outside")
        replaced.symlink_to(outside)
        browser.index.stop_event.set()  # Keep the prepared race-condition snapshot stable.
        browser.start()
        base = f"http://127.0.0.1:{browser.port}"
        query = urllib.parse.urlencode({"camera": "camera_front", "path": "day/clip.mp4"})
        try:
            with urllib.request.urlopen(f"{base}/api/meta") as response:
                meta = json.load(response)
            self.assertEqual(meta["cameras"], ["camera_front"])
            self.assertGreater(meta["storage"]["total"], 0)
            self.assertIn("percent", meta["storage"])
            with urllib.request.urlopen(f"{base}/api/recordings") as response:
                self.assertEqual(json.load(response)["total"], 3)

            watched_body = json.dumps({
                "camera": "camera_front", "path": "day/clip.mp4", "watched": True,
            }).encode()
            watched_request = urllib.request.Request(
                f"{base}/api/watched", data=watched_body, method="POST",
                headers={
                    "Content-Type": "application/json", "X-Reolink-CSRF": meta["csrf_token"],
                },
            )
            with urllib.request.urlopen(watched_request) as response:
                self.assertTrue(json.load(response)["watched"])
            with urllib.request.urlopen(f"{base}/api/recordings?watched=watched") as response:
                self.assertEqual(json.load(response)["total"], 1)

            status, value = chunked_json_request(
                base, "/api/watched",
                {"camera": "camera_front", "path": "day/clip.mp4", "watched": False},
                token=meta["csrf_token"],
            )
            self.assertEqual((status, value["watched"]), (200, False))
            status, value = chunked_json_request(
                base, "/api/watched",
                {"camera": "camera_front", "path": "day/clip.mp4", "watched": True},
                token=meta["csrf_token"], content_length=True,
            )
            self.assertEqual(status, 400)
            self.assertEqual(value["error"], "Ambiguous request body")

            active_query = urllib.parse.urlencode({"camera": "camera_front", "path": "day/active.mp4"})
            active_delete = urllib.request.Request(
                f"{base}/api/delete?{active_query}", method="POST",
                headers={"X-Reolink-CSRF": meta["csrf_token"]},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(active_delete)
            self.assertEqual(caught.exception.code, 409)
            caught.exception.close()
            self.assertTrue(active.exists())

            replaced_query = urllib.parse.urlencode({"camera": "camera_front", "path": "day/replaced.mp4"})
            replaced_delete = urllib.request.Request(
                f"{base}/api/delete?{replaced_query}", method="POST",
                headers={"X-Reolink-CSRF": meta["csrf_token"]},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(replaced_delete)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
            self.assertEqual(outside.read_bytes(), b"outside")

            missing_token = urllib.request.Request(f"{base}/api/delete?{query}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(missing_token)
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
            self.assertTrue(recording.exists())

            delete = urllib.request.Request(
                f"{base}/api/delete?{query}", method="POST",
                headers={"X-Reolink-CSRF": meta["csrf_token"]},
            )
            with urllib.request.urlopen(delete) as response:
                self.assertTrue(json.load(response)["deleted"])
            self.assertFalse(recording.exists())
            with urllib.request.urlopen(f"{base}/api/recordings") as response:
                self.assertEqual(json.load(response)["total"], 1)

            traversal = urllib.parse.urlencode({"camera": "camera_front", "path": "../outside.mp4"})
            unsafe = urllib.request.Request(
                f"{base}/api/delete?{traversal}", method="POST",
                headers={"X-Reolink-CSRF": meta["csrf_token"]},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(unsafe)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        finally:
            browser.stop()

    def test_bulk_delete_selected_and_filtered_with_stale_selection_protection(self):
        config = self.prepare()
        root = config.recording_root / "front"
        now = time.time() - 60
        recordings = {}
        for name, content in (("a.mp4", b"a"), ("b.mp4", b"bb"), ("c.mp4", b"ccc"), ("d.mp4", b"dddd")):
            path = root / name
            path.write_bytes(content)
            os.utime(path, (now, now))
            recordings[name] = path
        index_html = self.root / "index.html"
        index_html.write_text("test")
        browser = runtime.RecordingBrowser(
            config, host="127.0.0.1", port=0, allowed_clients={"127.0.0.1"},
            index_path=index_html, data_dir=self.data, scan_interval=3600,
        )
        browser.index._scan_all()
        browser.index.stop_event.set()
        browser.start()
        base = f"http://127.0.0.1:{browser.port}"
        try:
            with urllib.request.urlopen(f"{base}/api/meta") as response:
                token = json.load(response)["csrf_token"]

            def post_bulk(payload, *, csrf=token):
                return urllib.request.urlopen(urllib.request.Request(
                    f"{base}/api/delete-bulk", data=json.dumps(payload).encode(), method="POST",
                    headers={"Content-Type": "application/json", "X-Reolink-CSRF": csrf},
                ))

            selected = {
                "mode": "selected", "expected_count": 3,
                "recordings": [
                    {"camera": "camera_front", "path": "a.mp4"},
                    {"camera": "camera_front", "path": "b.mp4"},
                ],
            }
            with self.assertRaises(urllib.error.HTTPError) as caught:
                post_bulk(selected)
            self.assertEqual(caught.exception.code, 409)
            caught.exception.close()
            self.assertTrue(recordings["a.mp4"].exists())

            selected["expected_count"] = 2
            with post_bulk(selected) as response:
                result = json.load(response)
            self.assertEqual((result["deleted"], result["failed"], result["reclaimed"]), (2, 0, 3))
            self.assertFalse(recordings["a.mp4"].exists())
            self.assertFalse(recordings["b.mp4"].exists())

            filtered = {
                "mode": "filtered", "expected_count": 1, "expected_size": 999,
                "filters": {"camera": "camera_front", "q": "", "from": None, "to": None,
                            "watched": "all"},
                "excluded": [{"camera": "camera_front", "path": "d.mp4"}],
            }
            with self.assertRaises(urllib.error.HTTPError) as caught:
                post_bulk(filtered)
            self.assertEqual(caught.exception.code, 409)
            caught.exception.close()
            self.assertTrue(recordings["c.mp4"].exists())

            filtered["expected_size"] = 3
            with post_bulk(filtered) as response:
                result = json.load(response)
            self.assertEqual((result["requested"], result["deleted"], result["reclaimed"]), (1, 1, 3))
            self.assertFalse(recordings["c.mp4"].exists())
            self.assertTrue(recordings["d.mp4"].exists())
            with urllib.request.urlopen(f"{base}/api/recordings") as response:
                self.assertEqual(json.load(response)["total"], 1)

            no_csrf = {"mode": "selected", "expected_count": 1, "recordings": []}
            with self.assertRaises(urllib.error.HTTPError) as caught:
                post_bulk(no_csrf, csrf="")
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        finally:
            browser.stop()

    def test_plain_ftp_needs_explicit_opt_in(self):
        value = options()
        value["tls"]["require_tls"] = False
        with self.assertRaises(runtime.ConfigError):
            self.prepare(value)
        value["tls"]["allow_plain_ftp"] = True
        config = self.prepare(value)
        path = runtime.build_vsftpd_config(config, self.root / "run", self.root / "users")
        self.assertIn("force_local_logins_ssl=NO", path.read_text())
        value["tls"]["require_tls"] = True
        with self.assertRaises(runtime.ConfigError):
            self.prepare(value)

    def test_blank_pasv_address_rejected(self):
        value = options()
        value["pasv_address"] = ""
        with self.assertRaisesRegex(runtime.ConfigError, "pasv_address is required"):
            self.prepare(value)

    def test_retention_removes_only_old_regular_files_and_skips_symlink(self):
        config = self.prepare()
        old = config.recording_root / "front/old.mp4"
        fresh = config.recording_root / "front/fresh.mp4"
        outside = self.share / "outside.mp4"
        old.write_bytes(b"old")
        fresh.write_bytes(b"fresh")
        outside.write_bytes(b"outside")
        timestamp = time.time() - 3 * 86400
        os.utime(old, (timestamp, timestamp))
        (config.recording_root / "escape").symlink_to(self.share, target_is_directory=True)
        removed, reclaimed = runtime.remove_expired_files(config.recording_root, 2)
        self.assertEqual((removed, reclaimed), (1, 3))
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(outside.exists())

    def test_uid_map_is_persistent_and_does_not_contain_passwords(self):
        users = runtime.validate_users(options()["users"])
        first = runtime.allocate_uids(users, self.data)
        second = runtime.allocate_uids(tuple(reversed(users)), self.data)
        self.assertEqual(first, second)
        content = (self.data / "user_uids.json").read_text()
        self.assertNotIn("secret", content)

    def test_storage_permissions_allow_login_traversal_without_parent_listing(self):
        recording_root = self.media / "ReolinkSSD/reolink"
        nested_home = recording_root / "site/front"
        nested_home.mkdir(parents=True)
        shared_parent_home = recording_root / "site"
        runtime.configure_storage_permissions(
            recording_root,
            (shared_parent_home, nested_home),
            group_gid=os.getgid(),
            owner_uid=os.getuid(),
        )
        self.assertEqual(recording_root.stat().st_mode & 0o777, 0o710)
        self.assertEqual(shared_parent_home.stat().st_mode & 0o777, 0o770)
        self.assertEqual(nested_home.stat().st_mode & 0o777, 0o770)

    def test_options_json_parsing_and_free_space_use_recording_filesystem(self):
        options_path = self.data / "options.json"
        options_path.write_text(json.dumps(options()))
        loaded = runtime.load_options(options_path)
        config = self.prepare(loaded)
        usage = shutil.disk_usage(config.recording_root)
        with mock.patch.object(runtime.shutil, "disk_usage", return_value=usage):
            self.assertEqual(runtime.free_bytes(config.recording_root), usage.free)


if __name__ == "__main__":
    unittest.main()
