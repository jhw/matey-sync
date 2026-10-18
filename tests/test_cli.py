import logging

import pytest

from conftest import entry
from matey_sync import cli


@pytest.fixture(autouse=True)
def _restore_logger():
    yield
    log = logging.getLogger("matey_sync")
    log.handlers[:] = []
    log.propagate = True


def test_cli_end_to_end_logs_to_console(make, tmp_path, monkeypatch, capsys):
    client, _, session = make([entry("A=BASS.m8i", clip=True, author="bob")])
    monkeypatch.setattr(cli, "MateyClient", lambda **kw: client)
    card = tmp_path / "M8"
    (card / "Instruments").mkdir(parents=True)
    cache = tmp_path / "c"

    rc = cli.main(["bass", "--cache-dir", str(cache), "--m8",
                   "--m8-root", str(card)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "INFO" in out and "searching impbox.net/matey for 'bass'" in out
    assert "[1/1] bob/A=BASS.m8i" in out and "done:" in out and "M8 done" in out
    assert (card / "Instruments/Packs/matey/bass/A=BASS.m8i").exists()
    assert (cache / "bass/bob/A=BASS.mp3").exists()


def test_quiet_hides_info(make, tmp_path, monkeypatch, capsys):
    client, _, _ = make([entry("A.m8i")])
    monkeypatch.setattr(cli, "MateyClient", lambda **kw: client)
    assert cli.main(["a", "-q", "--cache-dir", str(tmp_path / "c")]) == 0
    assert capsys.readouterr().out == ""


def test_verbose_shows_requests(make, tmp_path, monkeypatch, capsys):
    client, _, _ = make([entry("A.m8i")])
    monkeypatch.setattr(cli, "MateyClient", lambda **kw: client)
    cli.main(["a", "-v", "--cache-dir", str(tmp_path / "c")])
    assert "DEBUG" in capsys.readouterr().out


def test_cli_m8_missing_gives_error_code(make, tmp_path, monkeypatch, capsys):
    client, _, _ = make([entry("A.m8i")])
    monkeypatch.setattr(cli, "MateyClient", lambda **kw: client)
    rc = cli.main(["", "--cache-dir", str(tmp_path / "c"), "--m8",
                   "--m8-root", str(tmp_path / "nope")])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


def test_default_delay_is_polite():
    assert cli.build_parser().parse_args([]).delay >= 1.0
