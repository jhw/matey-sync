# matey-sync

Mirror Dirtywave M8 instrument patches (`.m8i`) and their audio clips from
[impbox.net/matey](https://www.impbox.net/matey/) by search term, keep a local
cache, and copy the results to an M8.

Many patches on the site have no audio clip, so you can't hear them before
downloading. This tool fetches the clip (MP3) whenever one exists, so you can
audition patches locally.

## Install

    cd /Users/jhw/work/matey-sync
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e '.[dev]'

## Use

    matey-sync bass                      # download new patches + clips matching "bass"
    matey-sync strings --only-with-clip  # skip patches with no clip
    matey-sync bass --dry-run            # show what would be fetched, change nothing
    matey-sync bass --m8                 # ...then copy to /Volumes/M8/Instruments/Packs/matey/bass/<user>/
    matey-sync                           # no term: every patch on the site (folder "_all")
    matey-sync bass -v                   # also log every HTTP request and pause
    matey-sync bass -q                   # warnings and errors only

Run it again later and only what is new or changed is downloaded. Progress is
logged to the console with timestamps: what the search found, how many requests
the run needs and roughly how long that will take, one line per patch, and a
summary at the end. Exit code: 0 ok, 1 some patches failed, 2 stopped early.

## Where things go

The cache (default `<project>/tmp/`, git-ignored; override with `--cache-dir`
or `$MATEY_SYNC_CACHE`) is laid out as `{search term}/{user}/{patch}`:

    tmp/bass/ineffable-twaddle/BS=SLAPPEN D.m8i
    tmp/bass/ineffable-twaddle/BS=SLAPPEN D.mp3     <- the audio clip, if any
    tmp/strings/impbox/KOTOKAT.m8i
    tmp/.index.json                                 <- server date of every copy

- Folder names are made filesystem-safe (a hostile term or author name can't
  escape the cache). The term is lower-cased; an empty term is `_all`.
- A patch often matches several searches. If another term's folder already
  holds the same version, it is **copied locally rather than downloaded
  again**; the clip too.
- If a patch is re-uploaded on the site, each copy is refreshed the next time
  its term is synced.
- Authors sometimes appear under two spellings (`ineffable_twaddle` and
  `ineffable-twaddle`); they get separate folders, as the site lists them.

On the M8: `/Volumes/M8/Instruments/Packs/matey/<term>/<user>/*.m8i` (alongside your other packs; the
same layout as the cache) (clips are not copied;
files already on the card with identical content are skipped). `Instruments/`
must already exist on the card. Characters FAT can't store (`* ? : " < > |`
etc.) are replaced with `_` in the filename.

## Being kind to the server

This is someone's hobby site, so the client is deliberately gentle:

- One request at a time, **1 second apart by default** plus up to 25% random
  jitter (`--delay` to change it). A 200-patch first run takes several minutes.
- Nothing already cached is requested again.
- On HTTP 429/500/502/503/504 or a connection error it backs off (2s, 4s, 8s,
  honouring `Retry-After`, capped at 60s) and retries up to 3 times.
- If 5 patches in a row fail, the run stops instead of hammering a struggling
  server. Run it again later; finished patches aren't fetched twice.
- Honest `matey-sync` User-Agent; sizes are sanity-checked.

## How it works

The site is a single-page app over a small JSON API (no login needed):

| Request | Returns |
|---|---|
| `GET /matey/api/?search=<term>` | JSON list: `name, path, date, author, favs, desc, hasClip` |
| `GET /matey/api/<path>` | the raw `.m8i` file |
| `GET /matey/api/<path>/clip` | the audio clip (MP3); 404 if none |

Patch paths from the server are validated before use as local filenames.

## Tests

    pytest

The tests use a fake HTTP session and temporary directories; they need no
network and never touch a real M8.
