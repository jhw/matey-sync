from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from .cache import Cache
from .client import MateyClient, MateyError
from .models import Patch

log = logging.getLogger("matey_sync")

# If this many patches in a row fail (after the client's own retries), the
# server is unhappy or unreachable: stop rather than keep hammering it.
MAX_CONSECUTIVE_FAILURES = 5


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 90:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


@dataclass
class Job:
    patch: Patch
    need_patch: bool
    need_clip: bool
    update: bool
    local_src: Optional[Path]

    @property
    def clip_from_local(self) -> bool:
        return bool(self.local_src and self.need_patch and self.patch.has_clip
                    and self.local_src.with_name(self.patch.clip_name).is_file())

    @property
    def network_requests(self) -> int:
        n = 1 if self.need_patch and not self.local_src else 0
        if self.need_clip and not self.clip_from_local:
            n += 1
        return n

    def describe(self) -> str:
        parts = []
        if self.need_patch:
            parts.append("copy patch from another term's folder"
                         if self.local_src else "download patch")
        if self.need_clip:
            parts.append("copy clip locally" if self.clip_from_local
                         else "download clip")
        return " + ".join(parts)


@dataclass
class SyncReport:
    term: str = ""
    matched: List[Patch] = field(default_factory=list)
    new_patches: List[Patch] = field(default_factory=list)
    updated_patches: List[Patch] = field(default_factory=list)
    new_clips: List[Patch] = field(default_factory=list)
    copied_locally: List[Patch] = field(default_factory=list)
    already_cached: int = 0
    failed: List[Tuple[str, str]] = field(default_factory=list)
    aborted: bool = False
    dry_run: bool = False


def _plan(term: str, patches: List[Patch], cache: Cache,
          report: SyncReport) -> List[Job]:
    jobs = []
    for patch in patches:
        need_patch = cache.needs_patch(term, patch)
        need_clip = cache.needs_clip(term, patch, need_patch)
        if not need_patch and not need_clip:
            report.already_cached += 1
            continue
        jobs.append(Job(
            patch=patch, need_patch=need_patch, need_clip=need_clip,
            update=cache.is_update(term, patch),
            local_src=cache.find_local_copy(term, patch) if need_patch
            else None))
    return jobs


def sync(term: str, client: MateyClient, cache: Cache, *,
         only_with_clip: bool = False, dry_run: bool = False) -> SyncReport:
    """Search the site, then fetch whatever the local cache is missing.

    A patch is fetched if this term's folder has no copy or the server's date
    changed. If another term's folder already holds the same version it is
    copied locally instead. A clip is fetched whenever the site has one and
    we don't (so clips added after the first sync are picked up too).
    """
    report = SyncReport(term=term, dry_run=dry_run)

    log.info("searching impbox.net/matey for %r", term or "(everything)")
    patches = client.search(term)
    with_clip = sum(p.has_clip for p in patches)
    log.info("%d patches match (%d have an audio clip)",
             len(patches), with_clip)
    if only_with_clip:
        patches = [p for p in patches if p.has_clip]
        log.info("--only-with-clip: keeping %d", len(patches))
    report.matched = patches

    jobs = _plan(term, patches, cache, report)
    requests_needed = sum(j.network_requests for j in jobs)
    log.info("%d already up to date; %d to do (%d downloads)",
             report.already_cached, len(jobs), requests_needed)
    if requests_needed:
        eta = requests_needed * client.delay * (1 + client.jitter / 2)
        log.info("fetching one at a time, ~%.1fs apart: roughly %s",
                 client.delay, human_duration(eta))

    failures_in_a_row = 0
    for i, job in enumerate(jobs, 1):
        patch = job.patch
        prefix = f"[{i}/{len(jobs)}] {patch.author or 'unknown'}/{patch.path}"
        if dry_run:
            log.info("%s: would %s", prefix, job.describe())
            if job.need_patch:
                (report.updated_patches if job.update
                 else report.new_patches).append(patch)
                if job.local_src:
                    report.copied_locally.append(patch)
            if job.need_clip and not job.clip_from_local:
                report.new_clips.append(patch)
            continue

        started = time.monotonic()
        parts = []
        try:
            need_clip = job.need_clip
            if job.need_patch:
                if job.local_src:
                    clip_copied = cache.copy_local(term, patch, job.local_src)
                    parts.append("copied from local cache")
                    report.copied_locally.append(patch)
                    need_clip = need_clip and not clip_copied
                else:
                    data = client.download_patch(patch)
                    cache.store_patch(term, patch, data)
                    parts.append(f"patch {human_size(len(data))}")
                (report.updated_patches if job.update
                 else report.new_patches).append(patch)
            if need_clip:
                clip = client.download_clip(patch)
                if clip is None:
                    parts.append("no clip on server")
                else:
                    cache.store_clip(term, patch, clip)
                    report.new_clips.append(patch)
                    parts.append(f"clip {human_size(len(clip))}")
            log.info("%s: %s (%.1fs)", prefix, ", ".join(parts),
                     time.monotonic() - started)
            failures_in_a_row = 0
        except (MateyError, requests.RequestException, OSError) as e:
            report.failed.append((patch.path, str(e)))
            failures_in_a_row += 1
            log.warning("%s: FAILED - %s", prefix, e)
            if failures_in_a_row >= MAX_CONSECUTIVE_FAILURES:
                report.aborted = True
                log.error("%d failures in a row - stopping to avoid "
                          "hammering the server. Run again later; finished "
                          "patches won't be fetched twice.",
                          MAX_CONSECUTIVE_FAILURES)
                break
    return report
