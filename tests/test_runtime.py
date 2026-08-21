from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
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
