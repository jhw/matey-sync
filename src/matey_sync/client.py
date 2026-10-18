from __future__ import annotations

import logging
import random
import time
from typing import Callable, List, Optional
from urllib.parse import quote

import requests

from . import __version__
from .models import Patch, UnsafePath

log = logging.getLogger("matey_sync")

BASE_URL = "https://www.impbox.net/matey"
USER_AGENT = f"matey-sync/{__version__} (personal patch mirror)"
M8_MAGIC = b"M8VERSION"
MAX_PATCH_BYTES = 1_000_000      # real patches are a few hundred bytes
MAX_CLIP_BYTES = 25_000_000
RETRY_STATUS = {429, 500, 502, 503, 504}


class MateyError(Exception):
    """The site returned something we did not expect."""


def _retry_after(resp) -> Optional[float]:
    value = (getattr(resp, "headers", None) or {}).get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP-date; fall back to our own backoff


class MateyClient:
    """Polite client for the JSON API behind impbox.net/matey.

    Endpoints (all GET, no login needed):
      /api/?search=<term>      list of patch dicts (all patches if no term)
      /api/<path>              the raw .m8i file
      /api/<path>/clip         the audio clip (MP3); 404 if there isn't one

    Good-citizen behaviour: one request at a time, ``delay`` seconds (plus up
    to ``jitter`` extra, as a fraction) between requests, and on 429/5xx or a
    connection error it backs off exponentially (honouring Retry-After)
    before retrying a few times, then gives up on that request.
    """

    def __init__(self, base_url: str = BASE_URL, session=None,
                 delay: float = 1.0, jitter: float = 0.25,
                 timeout: float = 30.0, retries: int = 3,
                 backoff: float = 2.0, max_wait: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.base_url = base_url.rstrip("/")
        self.session = session if session is not None else requests.Session()
        self.delay = delay
        self.jitter = jitter
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.max_wait = max_wait
        self._sleep = sleep
        self._clock = clock
        self._last: Optional[float] = None
        self.requests_made = 0

    def _pace(self) -> None:
        if self._last is None:
            return
        gap = self.delay * (1 + random.uniform(0, self.jitter))
        wait = self._last + gap - self._clock()
        if wait > 0:
            log.debug("pausing %.2fs between requests", wait)
            self._sleep(wait)

    def _get(self, url: str, params: Optional[dict] = None):
        attempt = 0
        while True:
            self._pace()
            log.debug("GET %s%s", url, f" {params}" if params else "")
            try:
                self.requests_made += 1
                resp = self.session.get(
                    url, params=params, timeout=self.timeout,
                    headers={"User-Agent": USER_AGENT})
            except requests.RequestException as e:
                self._last = self._clock()
                if attempt >= self.retries:
                    raise
                wait = min(self.backoff * 2 ** attempt, self.max_wait)
                attempt += 1
                log.warning("request failed (%s); retry %d/%d in %.0fs",
                            e.__class__.__name__, attempt, self.retries, wait)
                self._sleep(wait)
                continue
            self._last = self._clock()
            if resp.status_code in RETRY_STATUS and attempt < self.retries:
                wait = min(_retry_after(resp)
                           or self.backoff * 2 ** attempt, self.max_wait)
                attempt += 1
                log.warning("server said HTTP %d; backing off %.0fs "
                            "(retry %d/%d)", resp.status_code, wait,
                            attempt, self.retries)
                self._sleep(wait)
                continue
            return resp

    def _file_url(self, path: str, suffix: str = "") -> str:
        return f"{self.base_url}/api/{quote(path, safe='')}{suffix}"

    def search(self, term: str = "") -> List[Patch]:
        """Patches matching ``term`` (all patches when it is empty).

        Entries with an unusable path are skipped, not fatal.
        """
        params = {"search": term} if term else None
        r = self._get(f"{self.base_url}/api/", params=params)
        if r.status_code != 200:
            raise MateyError(f"search returned HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as e:
            raise MateyError(f"search did not return JSON: {e}") from e
        if not isinstance(data, list):
            raise MateyError("search returned an unexpected JSON shape")
        patches, skipped = [], 0
        for item in data:
            try:
                patches.append(Patch.from_api(item))
            except (UnsafePath, AttributeError, TypeError, ValueError):
                skipped += 1
        if skipped:
            log.warning("ignored %d search results with unusable paths",
                        skipped)
        return patches

    def download_patch(self, patch: Patch) -> bytes:
        r = self._get(self._file_url(patch.path))
        if r.status_code != 200:
            raise MateyError(f"{patch.path}: HTTP {r.status_code}")
        data = r.content
        if not data.startswith(M8_MAGIC):
            raise MateyError(f"{patch.path}: not an M8 file")
        if len(data) > MAX_PATCH_BYTES:
            raise MateyError(f"{patch.path}: unexpectedly large "
                             f"({len(data)} bytes)")
        return data

    def download_clip(self, patch: Patch) -> Optional[bytes]:
        """The clip's bytes, or None if the site has no clip for this patch."""
        r = self._get(self._file_url(patch.path, "/clip"))
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise MateyError(f"{patch.path} clip: HTTP {r.status_code}")
        if not r.content:
            raise MateyError(f"{patch.path} clip: empty response")
        if len(r.content) > MAX_CLIP_BYTES:
            raise MateyError(f"{patch.path} clip: unexpectedly large "
                             f"({len(r.content)} bytes)")
        return r.content
