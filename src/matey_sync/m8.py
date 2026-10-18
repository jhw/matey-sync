from __future__ import annotations

import filecmp
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

from .cache import Cache
from .models import Patch, safe_term

log = logging.getLogger("matey_sync")

DEFAULT_M8_ROOT = Path("/Volumes/M8")
DEFAULT_INSTRUMENTS_DIR = "Instruments"
DEFAULT_SUBDIR = "Packs/matey"  # next to the other third-party packs

# Characters FAT (the M8's SD card) cannot hold in a filename.
_FAT_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class M8NotFound(Exception):
    """The M8 volume or its Instruments folder is not there."""


def fat_safe(filename: str) -> str:
    cleaned = _FAT_BAD.sub("_", filename).rstrip(" .")
    return cleaned or "_"


@dataclass
class M8Report:
    destination: Path
    copied: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    not_cached: List[str] = field(default_factory=list)
    dry_run: bool = False


def copy_to_m8(term: str, patches: Sequence[Patch], cache: Cache, *,
               m8_root: Path = DEFAULT_M8_ROOT,
               instruments_dir: str = DEFAULT_INSTRUMENTS_DIR,
               subdir: str = DEFAULT_SUBDIR,
               dry_run: bool = False) -> M8Report:
    """Copy cached ``.m8i`` files to ``<m8_root>/Instruments/Packs/matey/<term>/ by default``.

    One folder per search term, so patches are easy to browse on the device.
    Only the .m8i files go to the M8 (not the MP3 clips). Files already on
    the card with identical content are left alone. The Instruments folder
    must already exist; only the folders below it are created.
    """
    m8_root = Path(m8_root)
    if not m8_root.is_dir():
        raise M8NotFound(f"{m8_root} not found - is the M8 mounted?")
    base = m8_root / instruments_dir
    if not base.is_dir():
        raise M8NotFound(f"{base} not found - is this an M8 SD card?")
    dest = base / subdir / safe_term(term) if subdir else base / safe_term(term)

    report = M8Report(destination=dest, dry_run=dry_run)
    log.info("M8: %s %s", "checking (dry run)" if dry_run else "copying to",
             dest)
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    for patch in patches:
        src = cache.patch_file(term, patch)
        if not src.is_file():
            report.not_cached.append(patch.path)
            log.warning("M8: %s not in the local cache, skipped", patch.path)
            continue
        target = dest / fat_safe(patch.path)
        if target.is_file() and filecmp.cmp(src, target, shallow=False):
            report.unchanged.append(patch.path)
            log.debug("M8: %s already there", patch.path)
            continue
        if not dry_run:
            shutil.copyfile(src, target)
        report.copied.append(patch.path)
        log.info("M8: %s %s", "would copy" if dry_run else "copied",
                 target.name)
    return report
