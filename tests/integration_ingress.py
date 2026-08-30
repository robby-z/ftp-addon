#!/usr/bin/env python3
"""Exercise the recording browser through an Ingress-like client."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def open_url(url: str, *, headers: dict[str, str] | None = None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10)


def post_url(url: str, payload: dict | None = None, *, headers: dict[str, str] | None = None):
    request_headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        request_headers["Content-Type"] = "application/json"
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=request_headers, method="POST"), timeout=10,
    )


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

    with open_url(f"{base}/api/meta") as response:
        meta = json.load(response)
    assert meta["cameras"] == ["camera_front", "camera_garden"]
    assert meta["csrf_token"]
    assert meta["storage"]["total"] > 0
    assert 0 <= meta["storage"]["percent"] <= 100

    recordings = None
    for _ in range(30):
        with open_url(f"{base}/api/recordings") as response:
            recordings = json.load(response)
        if recordings["total"] == 2 and not recordings["status"]["scanning"]:
            break
        time.sleep(0.2)
    assert recordings is not None and recordings["total"] == 2
    assert [item["camera"] for item in recordings["items"]] == ["camera_garden", "camera_front"]

    query = urllib.parse.urlencode({"camera": "camera_front", "q": "clip", "page_size": 1})
    with open_url(f"{base}/api/recordings?{query}") as response:
        filtered = json.load(response)
    assert filtered["total"] == 1
    assert filtered["items"][0]["relative_path"] == "day/clip.mp4"
    assert filtered["filtered_size"] == 10

    with post_url(
        f"{base}/api/watched",
        {"camera": "camera_front", "path": "day/clip.mp4", "watched": True},
        headers={"X-Reolink-CSRF": meta["csrf_token"]},
    ) as response:
        assert json.load(response)["watched"] is True
    with open_url(f"{base}/api/recordings?watched=watched") as response:
        watched = json.load(response)
    assert watched["total"] == 1 and watched["items"][0]["camera"] == "camera_front"

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

    bulk_payload = {
        "mode": "filtered", "expected_count": 1, "expected_size": 12,
        "filters": {
            "camera": "camera_garden", "q": "", "from": None, "to": None, "watched": "all",
        },
        "excluded": [],
    }
    try:
        post_url(f"{base}/api/delete-bulk", bulk_payload)
    except urllib.error.HTTPError as err:
        try:
            assert err.code == 403
        finally:
            err.close()
    else:
        raise AssertionError("Bulk delete without CSRF token unexpectedly succeeded")

    with post_url(
        f"{base}/api/delete-bulk", bulk_payload,
        headers={"X-Reolink-CSRF": meta["csrf_token"]},
    ) as response:
        deleted = json.load(response)
    assert deleted["deleted"] == 1 and deleted["reclaimed"] == 12
    with open_url(f"{base}/api/recordings") as response:
        assert json.load(response)["total"] == 1

    print("Ingress table, filters, deletion, isolation, and range-streaming checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
