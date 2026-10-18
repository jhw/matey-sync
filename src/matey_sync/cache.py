from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from .models import Patch, safe_segment, safe_term


def default_cache_dir() -> Path:
    """``<project>/tmp`` when run from a source checkout, else ``./tmp``.

    Override with the MATEY_SYNC_CACHE environment variable or --cache-dir.
    """
    env = os.environ.get("MATEY_SYNC_CACHE")
    if env:
        return Path(env).expanduser()
    project = Path(__file__).resolve().parents[2]
    if (project / "pyproject.toml").is_file():
        return project / "tmp"
    return Path.cwd() / "tmp"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


class Cache:
    """Local mirror laid out as ``<term>/<user>/<patch>``::

        tmp/bass/ineffable-twaddle/BS=SLAPPEN D.m8i
        tmp/bass/ineffable-twaddle/BS=SLAPPEN D.mp3     <- its audio clip
        tmp/.index.json

    The same patch can sit under several terms. ``.index.json`` records the
    server date of every copy, so (a) a re-uploaded patch is noticed per copy,
    and (b) a patch already fetched under another term is copied locally
    instead of being downloaded again.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.index_path = self.root / ".index.json"
        self.index: Dict[str, dict] = self._load_index()

    # ---- index ---------------------------------------------------------
    def _load_index(self) -> Dict[str, dict]:
        try:
            data = json.loads(self.index_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_index(self) -> None:
        body = json.dumps(self.index, indent=2, sort_keys=True).encode()
        _atomic_write(self.index_path, body)

    def _rel(self, term: str, patch: Patch) -> Path:
        return (Path(safe_term(term))
                / safe_segment(patch.author, "_unknown") / patch.path)

    def _locations(self, patch: Patch) -> Dict[str, str]:
        return self.index.get(patch.path, {}).get("locations", {})

    def _record(self, term: str, patch: Patch) -> None:
        entry = self.index.setdefault(patch.path, {"locations": {}})
        entry.update(name=patch.name, author=patch.author,
                     has_clip=patch.has_clip)
        entry["locations"][self._rel(term, patch).as_posix()] = patch.date
        self.save_index()

    # ---- paths ---------------------------------------------------------
    def patch_file(self, term: str, patch: Patch) -> Path:
        return self.root / self._rel(term, patch)

    def clip_file(self, term: str, patch: Patch) -> Path:
        return self.patch_file(term, patch).with_name(patch.clip_name)

    def term_dir(self, term: str) -> Path:
        return self.root / safe_term(term)

    # ---- questions -----------------------------------------------------
    def needs_patch(self, term: str, patch: Patch) -> bool:
        rel = self._rel(term, patch).as_posix()
        return (not self.patch_file(term, patch).is_file()
                or self._locations(patch).get(rel) != patch.date)

    def is_update(self, term: str, patch: Patch) -> bool:
        """True if we hold an older copy of this patch under this term."""
        return self.patch_file(term, patch).is_file() and \
            self.needs_patch(term, patch)

    def needs_clip(self, term: str, patch: Patch,
                   patch_refreshed: bool) -> bool:
        return patch.has_clip and (patch_refreshed or
                                   not self.clip_file(term, patch).is_file())

    def find_local_copy(self, term: str, patch: Patch) -> Optional[Path]:
        """An up-to-date copy of this patch under another term, if any."""
        target = self.patch_file(term, patch)
        for rel, date in self._locations(patch).items():
            candidate = self.root / rel
            if date == patch.date and candidate != target \
                    and candidate.is_file():
                return candidate
        return None

    # ---- writes --------------------------------------------------------
    def store_patch(self, term: str, patch: Patch, data: bytes) -> None:
        _atomic_write(self.patch_file(term, patch), data)
        self._record(term, patch)

    def store_clip(self, term: str, patch: Patch, data: bytes) -> None:
        _atomic_write(self.clip_file(term, patch), data)

    def copy_local(self, term: str, patch: Patch, src: Path) -> bool:
        """Copy ``src`` (and its clip, if it has one) to this term's folder.

        Returns True if a clip was copied too.
        """
        _atomic_write(self.patch_file(term, patch), src.read_bytes())
        self._record(term, patch)
        src_clip = src.with_name(patch.clip_name)
        if patch.has_clip and src_clip.is_file():
            _atomic_write(self.clip_file(term, patch), src_clip.read_bytes())
            return True
        return False
