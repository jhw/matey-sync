import requests

from conftest import FakeSession, Resp, entry
from matey_sync.client import MateyClient, MateyError
from matey_sync.models import Patch
import pytest


def make_client(entries=None, **kw):
    sleeps = []
    session = FakeSession(entries or [entry("A.m8i")])
    client = MateyClient(base_url="https://x.test/matey", session=session,
                         sleep=sleeps.append, clock=lambda: 0.0, **kw)
    return client, session, sleeps


def test_requests_are_spaced_by_delay():
    client, session, sleeps = make_client(delay=1.0, jitter=0)
    p = Patch.from_api(entry("A.m8i", clip=True))
    client.search("a")
    client.download_patch(p)
    client.download_clip(p)
    assert sleeps == [1.0, 1.0]       # none before the first request


def test_jitter_only_adds_time():
    client, _, sleeps = make_client(delay=1.0, jitter=0.5)
    client.search("a")
    client.search("a")
    assert 1.0 <= sleeps[0] <= 1.5


def test_retries_503_then_succeeds_honouring_retry_after():
    client, session, sleeps = make_client(delay=0, jitter=0)
    session.scripted = [Resp(503, headers={"Retry-After": "7"})]
    assert client.search("a")
    assert 7.0 in sleeps and len(session.calls) == 2


def test_exponential_backoff_without_retry_after_and_cap():
    client, session, sleeps = make_client(delay=0, jitter=0, backoff=2.0,
                                          max_wait=5.0)
    session.scripted = [Resp(429), Resp(429), Resp(429)]
    client.search("a")
    assert sleeps == [2.0, 4.0, 5.0]  # 2, 4, then capped at 5 (not 8)


def test_gives_up_after_retries():
    client, session, _ = make_client(delay=0, jitter=0, retries=2)
    session.scripted = [Resp(500)] * 5
    with pytest.raises(MateyError):
        client.search("a")
    assert len(session.calls) == 3    # 1 try + 2 retries


def test_connection_errors_are_retried_then_raised():
    client, session, sleeps = make_client(delay=0, jitter=0, retries=2)
    session.scripted = [requests.ConnectionError("boom")] * 3
    with pytest.raises(requests.ConnectionError):
        client.search("a")
    assert len(session.calls) == 3 and sleeps == [2.0, 4.0]


def test_404_is_not_retried():
    client, session, _ = make_client()
    p = Patch.from_api(entry("A.m8i", clip=False))
    assert client.download_clip(p) is None
    assert len(session.calls) == 1


def test_rejects_non_m8_download():
    client, session, _ = make_client()
    session.scripted = [Resp(200, b"<html>hi</html>")]
    with pytest.raises(MateyError):
        client.download_patch(Patch.from_api(entry("A.m8i")))
