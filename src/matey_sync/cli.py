from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import requests

from . import __version__
from .cache import Cache, default_cache_dir
from .client import BASE_URL, MateyClient, MateyError
from .m8 import (DEFAULT_INSTRUMENTS_DIR, DEFAULT_M8_ROOT, DEFAULT_SUBDIR,
                 M8NotFound, copy_to_m8)
from .sync import sync

log = logging.getLogger("matey_sync")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="matey-sync",
        description="Mirror M8 patches (and audio clips) matching a search "
                    "term from impbox.net/matey into <cache>/<term>/<user>/, "
                    "optionally copying them to an M8 SD card.")
    p.add_argument("term", nargs="?", default="",
                   help="search term, e.g. bass or strings "
                        "(omit to match every patch)")
    p.add_argument("--cache-dir", type=Path, default=None,
                   help="local cache (default: <project>/tmp, or "
                        "$MATEY_SYNC_CACHE)")
    p.add_argument("--only-with-clip", action="store_true",
                   help="ignore patches that have no audio clip")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be downloaded/copied, change nothing")
    p.add_argument("--m8", action="store_true",
                   help="copy matching patches to the M8 after syncing")
    p.add_argument("--m8-root", type=Path, default=DEFAULT_M8_ROOT,
                   help=f"M8 mount point (default {DEFAULT_M8_ROOT})")
    p.add_argument("--m8-subdir", default=DEFAULT_SUBDIR,
                   help=f"folder inside {DEFAULT_INSTRUMENTS_DIR}/ on the M8; "
                        f"patches go in <subdir>/<term>/ "
                        f"(default '{DEFAULT_SUBDIR}')")
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds between requests to the site (default 1.0, "
                        "plus up to 25%% random jitter)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also log every HTTP request and pause")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="only log warnings and errors")
    p.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    p.add_argument("--version", action="version",
                   version=f"matey-sync {__version__}")
    return p


def setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING if quiet \
        else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"))
    log.handlers[:] = [handler]
    log.setLevel(level)
    log.propagate = False


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.quiet)

    cache = Cache(args.cache_dir or default_cache_dir())
    client = MateyClient(base_url=args.base_url, delay=args.delay)
    log.info("cache: %s", cache.root)

    try:
        report = sync(args.term, client, cache,
                      only_with_clip=args.only_with_clip,
                      dry_run=args.dry_run)
    except (MateyError, requests.RequestException) as e:
        log.error("%s", e)
        return 1

    verb = "would add" if report.dry_run else "added"
    log.info("done: %d match; %s %d new + %d updated patches, %d clips "
             "(%d patches reused from other terms); %d already up to date; "
             "%d HTTP requests in total",
             len(report.matched), verb, len(report.new_patches),
             len(report.updated_patches), len(report.new_clips),
             len(report.copied_locally), report.already_cached,
             client.requests_made)
    if report.failed:
        log.warning("%d failed: %s", len(report.failed),
                    ", ".join(p for p, _ in report.failed))

    status = 2 if report.aborted else 1 if report.failed else 0
    if args.m8:
        try:
            m = copy_to_m8(args.term, report.matched, cache,
                           m8_root=args.m8_root, subdir=args.m8_subdir,
                           dry_run=args.dry_run)
        except M8NotFound as e:
            log.error("%s", e)
            return 1
        log.info("M8 done: %s %d, %d already there%s",
                 "would copy" if m.dry_run else "copied", len(m.copied),
                 len(m.unchanged),
                 f", {len(m.not_cached)} not in cache" if m.not_cached
                 else "")
    return status


if __name__ == "__main__":
    sys.exit(main())
