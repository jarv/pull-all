#!/usr/bin/env python3
"""pull-all: fast-forward every git repo found in the subdirectories of a directory.

A repo is only touched if it is on its default branch (main/master) and its
working tree is clean. Everything else gets a warning and is left alone.
Standard library only.
"""

import argparse
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Result statuses
UPDATED, CURRENT, SKIPPED, FAILED = "updated", "current", "skipped", "failed"

ICONS = {UPDATED: "✔", CURRENT: "✔", SKIPPED: "⚠", FAILED: "✖"}
# ANSI codes picked to read well on a dark background.
COLORS = {UPDATED: "1;32", CURRENT: "2", SKIPPED: "33", FAILED: "1;31"}
CYAN, DIM, BOLD = "36", "2", "1"


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------

_procs: set = set()
_procs_lock = threading.Lock()
_cancelled = threading.Event()


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # started in its own session
    except (ProcessLookupError, PermissionError):
        pass


def kill_all():
    _cancelled.set()
    with _procs_lock:
        for p in list(_procs):
            _kill(p)


def git(repo, *args, timeout=120):
    """Run git in repo. Returns (returncode, stdout, stderr), stripped."""
    if _cancelled.is_set():
        raise Cancelled
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # never block on a credential prompt
        "GIT_OPTIONAL_LOCKS": "0",  # `git status` shouldn't fight other git procs
        "LC_ALL": "C",
    }
    proc = subprocess.Popen(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,  # detaches from the tty so ssh can't prompt either
    )
    with _procs_lock:
        _procs.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        proc.communicate()
        return 124, "", "timed out"
    finally:
        with _procs_lock:
            _procs.discard(proc)
    if _cancelled.is_set():
        raise Cancelled
    return proc.returncode, out.strip(), err.strip()


def default_branch(repo, timeout):
    """Best-effort local detection of the repo's default branch (no network)."""
    rc, out, _ = git(repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD", timeout=timeout)
    if rc == 0 and out.startswith("origin/"):
        return out[len("origin/"):]
    for prefix in ("refs/remotes/origin/", "refs/heads/"):
        for cand in ("main", "master"):
            rc, _, _ = git(repo, "show-ref", "--verify", "--quiet", prefix + cand, timeout=timeout)
            if rc == 0:
                return cand
    return None


def short_error(err):
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    if not lines:
        return "git pull failed"
    pick = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))), lines[-1])
    for prefix in ("fatal: ", "error: "):
        if pick.startswith(prefix):
            pick = pick[len(prefix):]
    return pick


def process_repo(repo: Path, timeout: int) -> Result:
    name = repo.name

    def skip(why):
        return Result(name, SKIPPED, f"unable to pull: {why}")

    rc, branch, _ = git(repo, "symbolic-ref", "--short", "-q", "HEAD", timeout=timeout)
    if rc != 0:
        return skip("detached HEAD")

    default = default_branch(repo, timeout)
    if default is None:
        return skip("can't determine default branch")
    if branch != default:
        return skip(f"on '{branch}', not '{default}'")

    rc, out, err = git(repo, "status", "--porcelain", timeout=timeout)
    if rc != 0:
        return Result(name, FAILED, short_error(err))
    if out:
        return skip("working tree not clean")

    _, before, _ = git(repo, "rev-parse", "HEAD", timeout=timeout)
    rc, _, err = git(repo, "pull", "--ff-only", "--quiet", timeout=timeout)
    if rc != 0:
        return Result(name, FAILED, short_error(err))
    _, after, _ = git(repo, "rev-parse", "HEAD", timeout=timeout)

    if before == after:
        return Result(name, CURRENT, "up to date")
    rc, count, _ = git(repo, "rev-list", "--count", f"{before}..{after}", timeout=timeout)
    return Result(name, UPDATED, f"+{count} commit{'s' if count != '1' else ''}" if rc == 0 else "updated")


def find_repos(root: Path):
    repos = []
    for p in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if p.name.startswith(".") or not p.is_dir():
            continue
        if (p / ".git").exists():  # dir for clones, file for worktrees/submodules
            repos.append(p)
    return repos


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


class Painter:
    def __init__(self, color):
        self.color = color

    def __call__(self, code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text


def format_result(res: Result, name_w: int, paint, width=None):
    prefix_len = 2 + name_w + 2  # icon + space, name, two spaces
    detail = res.detail
    if width and prefix_len + len(detail) > width - 1:
        detail = detail[: max(0, width - 1 - prefix_len - 1)] + "…"
    code = COLORS[res.status]
    name = res.name.ljust(name_w)
    return f"{paint(code, ICONS[res.status])} {paint(BOLD, name) if res.status != CURRENT else paint(DIM, name)}  {paint(code, detail)}"


def format_active(name, frame, paint, width=None):
    if width and len(name) + 2 > width - 1:
        name = name[: width - 4] + "…"
    return f"{paint(CYAN, frame)} {name}"


def summarize(results, elapsed, paint):
    counts = {s: sum(1 for r in results if r.status == s) for s in (UPDATED, CURRENT, SKIPPED, FAILED)}
    labels = {UPDATED: "updated", CURRENT: "up to date", SKIPPED: "skipped", FAILED: "failed"}
    parts = [paint(COLORS[s], f"{n} {labels[s]}") for s, n in counts.items() if n]
    return f"{', '.join(parts)} {paint(DIM, f'({elapsed:.1f}s)')}"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def run(root: Path, jobs: int, timeout: int, color: bool) -> int:
    repos = find_repos(root)
    if not repos:
        print(f"no git repos found in {root}")
        return 0

    out = sys.stdout
    tty = out.isatty()
    paint = Painter(color)
    name_w = max(len(r.name) for r in repos)

    done: "queue.Queue[Result]" = queue.Queue()
    active: dict = {}  # name -> start time
    lock = threading.Lock()

    def worker(repo: Path):
        with lock:
            active[repo.name] = time.monotonic()
        try:
            res = process_repo(repo, timeout)
        except Cancelled:
            return
        except Exception as e:  # never let one repo kill the run
            res = Result(repo.name, FAILED, str(e))
        finally:
            with lock:
                active.pop(repo.name, None)
        done.put(res)

    results: list = []
    live_lines = 0
    frame_i = 0
    start = time.monotonic()

    def render(new):
        """Print finished lines, then redraw the spinner block beneath them."""
        nonlocal live_lines, frame_i
        width = shutil.get_terminal_size((80, 24)).columns
        buf = []
        if live_lines:
            buf.append(f"\x1b[{live_lines}F")  # back to start of the live block
        buf.append("\x1b[J")  # clear it
        for res in new:
            buf.append(format_result(res, name_w, paint, width) + "\n")
        with lock:
            running = sorted(active.items(), key=lambda kv: kv[1])
        frame = SPINNER[frame_i % len(SPINNER)]
        frame_i += 1
        for name, _ in running:
            buf.append(format_active(name, frame, paint, width) + "\n")
        live_lines = len(running)
        out.write("".join(buf))
        out.flush()

    if tty:
        out.write("\x1b[?25l")  # hide cursor
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for r in repos:
                pool.submit(worker, r)
            try:
                while len(results) < len(repos):
                    new = []
                    try:
                        new.append(done.get(timeout=0.08))
                        while True:
                            new.append(done.get_nowait())
                    except queue.Empty:
                        pass
                    results.extend(new)
                    if tty:
                        render(new)
                    else:
                        for res in new:
                            print(format_result(res, name_w, paint))
            except KeyboardInterrupt:
                kill_all()
                pool.shutdown(wait=True, cancel_futures=True)
                if tty:
                    out.write(f"\x1b[{live_lines}F\x1b[J" if live_lines else "")
                print(paint(COLORS[SKIPPED], "interrupted"))
                return 130
    finally:
        if tty:
            out.write("\x1b[?25h")
            out.flush()

    print(summarize(results, time.monotonic() - start, paint))
    return 1 if any(r.status == FAILED for r in results) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="pull-all",
        description="Pull the latest changes in every git repo under a directory, "
        "if it is on its default branch with a clean working tree.",
    )
    ap.add_argument("path", nargs="?", default=".", help="directory containing repos (default: .)")
    ap.add_argument("-j", "--jobs", type=int, default=8, metavar="N", help="repos to pull concurrently (default: 8)")
    ap.add_argument("-t", "--timeout", type=int, default=120, metavar="SECS", help="per-git-command timeout (default: 120)")
    ap.add_argument("--no-color", action="store_true", help="disable colors (also honors NO_COLOR)")
    args = ap.parse_args(argv)

    if args.jobs < 1:
        ap.error("--jobs must be >= 1")
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        ap.error(f"not a directory: {root}")

    color = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ
    return run(root, args.jobs, args.timeout, color)


if __name__ == "__main__":
    sys.exit(main())
