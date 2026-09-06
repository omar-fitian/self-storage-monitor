"""Getting a page over plain HTTP.
"""

from __future__ import annotations

import gzip
import urllib.request


_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}


def fetch(url: str, timeout: int = 30) -> str:
    """Fetch one page over plain HTTP, decompressing gzip if served."""
    request = urllib.request.Request(url, headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")
