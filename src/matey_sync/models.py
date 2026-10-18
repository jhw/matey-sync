from __future__ import annotations

import re
from dataclasses import dataclass


_BAD_SEGMENT_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_segment(value: str, fallback: str = "_", max_len: int = 100) -> str:
    """Make ``value`` usable as ONE directory name (no separators, no dots-only).

    Used for the search term and author folders, both of which come from the
    user or the remote server.
    """
    s = _BAD_SEGMENT_CHARS.sub("_", " ".join(str(value or "").split()))
    s = s.strip(" .")[:max_len].strip(" .")
    return s or fallback


def safe_term(term: str) -> str:
    """Folder name for a search term ('' means the whole catalogue)."""
    return safe_segment((term or "").lower(), fallback="_all")


class UnsafePath(ValueError):
    """The server gave us a patch path we refuse to use as a local filename."""


_PATCH_EXT = ".m8i"


def validate_patch_path(path: str) -> str:
    """Return ``path`` if it is a plain ``something.m8i`` filename, else raise.

    Paths come from a remote server and become local filenames, so reject
    anything that could escape the cache directory or is not a patch file.
    """
    if not isinstance(path, str) or not path:
        raise UnsafePath("empty path")
    if "/" in path or "\\" in path or "\x00" in path:
        raise UnsafePath(f"path contains a separator: {path!r}")
    if path.startswith("."):
        raise UnsafePath(f"path starts with a dot: {path!r}")
    if not path.lower().endswith(_PATCH_EXT) or len(path) == len(_PATCH_EXT):
        raise UnsafePath(f"not a {_PATCH_EXT} file: {path!r}")
    return path


@dataclass(frozen=True)
class Patch:
    name: str
    path: str  # e.g. "LD=CSW-STR1.m8i" - also the local filename
    date: str  # ISO timestamp from the server; used to spot re-uploads
    author: str = ""
    favs: int = 0
    desc: str = ""
    has_clip: bool = False

    @classmethod
    def from_api(cls, d: dict) -> "Patch":
        return cls(
            name=str(d.get("name", "")),
            path=validate_patch_path(d.get("path")),
            date=str(d.get("date") or ""),
            author=str(d.get("author") or ""),
            favs=int(d.get("favs") or 0),
            desc=str(d.get("desc") or ""),
            has_clip=bool(d.get("hasClip")),
        )

    @property
    def clip_name(self) -> str:
        """Local filename for the audio clip (the site serves MP3)."""
        return self.path[: -len(_PATCH_EXT)] + ".mp3"
