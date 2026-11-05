# pull-all

Run in a directory full of git repos. For each immediate subdirectory that is a
repo, if it is on its default branch (`main`/`master`) with a clean working
tree, run `git pull --ff-only`. Anything else gets a warning and is left alone.

Python 3 standard library only.

```
pull-all [-j N] [-t SECS] [--no-color] [path]
```

- `-j N` repos pulled concurrently (default 8)
- `-t SECS` per-git-command timeout (default 120)
- `path` directory to scan (default `.`)

Output is one line per repo plus a summary. A spinner shows repos in flight
when stdout is a terminal. Exit code is 1 if any pull failed (skips are warnings,
not failures), 130 on Ctrl-C.

Notes:

- Default branch comes from `origin/HEAD`, falling back to `main`, then `master`.
  No network calls are made to work it out.
- Untracked files count as "not clean".
- Only fast-forward pulls are done; diverged branches are reported as failed.
- Hidden directories and non-repos are ignored.

## Install

```
ln -s ~/src/jarv/pull-all/pull_all.py ~/.local/bin/pull-all
```

## Tests

```
python3 -m unittest discover -s tests
```
