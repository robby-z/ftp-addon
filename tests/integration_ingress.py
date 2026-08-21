#!/usr/bin/env python3
"""Exercise the read-only recording browser through an Ingress-like client."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def open_url(url: str, *, headers: dict[str, str] | None = None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--expect-forbidden", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    if args.expect_forbidden:
        try:
            open_url(f"{base}/api/users")
        except urllib.error.HTTPError as err:
            try:
                if err.code != 403:
                    raise AssertionError(f"Expected 403, got {err.code}")
            finally:
                err.close()
            print("Non-Ingress client rejection passed")
            return 0
        raise AssertionError("Non-Ingress client unexpectedly reached the browser")

    with open_url(f"{base}/", headers={"X-Ingress-Path": "/api/hassio_ingress/test-token"}) as response:
        html = response.read().decode("utf-8")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert '"/api/hassio_ingress/test-token"' in html
        assert "Reolink-Aufnahmen" in html

    with open_url(f"{base}/api/users") as response:
        users = json.load(response)["users"]
    assert [user["username"] for user in users] == ["camera_front", "camera_garden", "viewer"]
    assert all("password" not in user for user in users)

    list_query = urllib.parse.urlencode({"user": "camera_front", "path": "day"})
    with open_url(f"{base}/api/list?{list_query}") as response:
        listing = json.load(response)
    assert [entry["name"] for entry in listing["entries"]] == ["clip.mp4"]
    assert listing["entries"][0]["mime"] == "video/mp4"

    media_query = urllib.parse.urlencode({"user": "camera_front", "path": "day/clip.mp4"})
    with open_url(f"{base}/media?{media_query}", headers={"Range": "bytes=2-6"}) as response:
        assert response.status == 206
        assert response.headers["Accept-Ranges"] == "bytes"
        assert response.headers["Content-Range"] == "bytes 2-6/10"
        assert response.read() == b"23456"

    traversal_query = urllib.parse.urlencode({"user": "camera_front", "path": "../viewer"})
    try:
        open_url(f"{base}/api/list?{traversal_query}")
    except urllib.error.HTTPError as err:
        try:
            assert err.code == 400
        finally:
            err.close()
    else:
        raise AssertionError("Traversal request unexpectedly succeeded")

    print("Ingress browser, listing, isolation, and range-streaming checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
