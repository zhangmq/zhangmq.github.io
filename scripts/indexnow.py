#!/usr/bin/env python3
"""Submit every URL in the site's sitemap to IndexNow (Bing et al.).

The key file must already be deployed at https://<host>/<key>.txt and its
content must be exactly the key. Run after a deployment has gone live.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HOST = "zhangmq.github.io"
KEY = "234698b6768941abb1320b4eab36efc3"
SITEMAP = f"https://{HOST}/sitemap.xml"
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"
SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "vsr-blog-indexnow/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def sitemap_urls(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    return [el.text.strip() for el in root.findall("sm:url/sm:loc", SM_NS) if el.text]


def wait_for_key(timeout: int = 180) -> bool:
    """CDN may lag behind the deploy; give the key file a chance to appear."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if fetch(KEY_LOCATION).decode().strip() == KEY:
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError):
            pass
        time.sleep(5)
    return False


def submit(urls: list[str]) -> tuple[int, str]:
    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.read().decode(errors="replace")


def main() -> int:
    if not wait_for_key():
        print(f"key file not reachable at {KEY_LOCATION}", file=sys.stderr)
        return 1

    urls = sitemap_urls(fetch(SITEMAP))
    if not urls:
        print("sitemap contains no URLs", file=sys.stderr)
        return 1
    print(f"sitemap urls: {len(urls)}")

    status, body = submit(urls)
    print(f"indexnow status: {status} {body.strip()[:200]}")
    return 0 if status in (200, 202) else 1


if __name__ == "__main__":
    sys.exit(main())
