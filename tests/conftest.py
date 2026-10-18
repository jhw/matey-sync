import json
from urllib.parse import quote

import pytest

from matey_sync.cache import Cache
from matey_sync.client import MateyClient

M8 = b"M8VERSION\x00" + b"\x01" * 20
CLIP = b"\xff\xfbd" + b"\x00" * 50


def entry(path, date="2025-01-01T00:00:00+00:00", clip=False, author="a",
          **kw):
    d = {"name": path[:-4], "path": path, "date": date, "author": author,
         "favs": 0, "desc": "", "hasClip": clip}
    d.update(kw)
    return d


class Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}

    def json(self):
        return json.loads(self.content)


class FakeSession:
    """Stands in for requests.Session; routes by URL like the real site."""

    def __init__(self, entries):
        self.entries = entries
        self.calls = []
        self.fail = set()      # patch paths whose download should 500
        self.scripted = []     # responses handed out first, in order

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params))
        if self.scripted:
            nxt = self.scripted.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        if url.endswith("/api/"):
            term = (params or {}).get("search", "").lower()
            hits = [e for e in self.entries
                    if term in (e["name"] + e["desc"]).lower()]
            return Resp(200, json.dumps(hits).encode())
        tail = url.split("/api/", 1)[1]
        for e in self.entries:
            enc = quote(e["path"], safe="")
            if e["path"] in self.fail and tail.startswith(enc):
                return Resp(500)
            if tail == enc:
                return Resp(200, M8)
            if tail == enc + "/clip":
                return Resp(200, CLIP) if e["hasClip"] else Resp(404)
        return Resp(404)


@pytest.fixture
def make(tmp_path):
    def _make(entries):
        session = FakeSession(entries)
        client = MateyClient(base_url="https://x.test/matey",
                             session=session, delay=0, jitter=0,
                             sleep=lambda s: None)
        return client, Cache(tmp_path / "cache"), session
    return _make
