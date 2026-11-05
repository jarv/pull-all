import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "pull-all"
_loader = importlib.machinery.SourceFileLoader("pull-all", str(SCRIPT))
_spec = importlib.util.spec_from_loader("pull-all", _loader)
pull_all = importlib.util.module_from_spec(_spec)
_loader.exec_module(pull_all)


def sh(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def commit(repo, name):
    (Path(repo) / name).write_text(name)
    sh(repo, "add", name)
    sh(repo, "commit", "-m", name)


class PullAllTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def make_remote(self, name="remote", branch="main"):
        """A bare remote seeded with one commit, plus an 'upstream' clone to push new commits from."""
        bare = self.root / f"{name}.git"
        sh(self.root, "init", "-q", "--bare", "-b", branch, str(bare))
        seed = self.root / f"{name}-seed"
        sh(self.root, "clone", "-q", str(bare), str(seed))
        sh(seed, "checkout", "-q", "-B", branch)
        commit(seed, "a")
        sh(seed, "push", "-q", "-u", "origin", branch)
        return bare, seed

    def clone(self, bare, name):
        sh(self.work, "clone", "-q", str(bare), name)
        return self.work / name

    def test_updated(self):
        bare, seed = self.make_remote()
        repo = self.clone(bare, "r")
        commit(seed, "b"); commit(seed, "c"); sh(seed, "push", "-q")
        res = pull_all.process_repo(repo, 30)
        self.assertEqual((res.status, res.detail), (pull_all.UPDATED, "+2 commits"))

    def test_up_to_date(self):
        bare, _ = self.make_remote()
        res = pull_all.process_repo(self.clone(bare, "r"), 30)
        self.assertEqual(res.status, pull_all.CURRENT)

    def test_master_default(self):
        bare, seed = self.make_remote(branch="master")
        repo = self.clone(bare, "r")
        commit(seed, "b"); sh(seed, "push", "-q")
        self.assertEqual(pull_all.process_repo(repo, 30).status, pull_all.UPDATED)

    def test_dirty(self):
        bare, _ = self.make_remote()
        repo = self.clone(bare, "r")
        (repo / "a").write_text("changed")
        res = pull_all.process_repo(repo, 30)
        self.assertEqual(res.status, pull_all.SKIPPED)
        self.assertIn("not clean", res.detail)

    def test_untracked_counts_as_dirty(self):
        bare, _ = self.make_remote()
        repo = self.clone(bare, "r")
        (repo / "new").write_text("x")
        self.assertEqual(pull_all.process_repo(repo, 30).status, pull_all.SKIPPED)

    def test_other_branch(self):
        bare, _ = self.make_remote()
        repo = self.clone(bare, "r")
        sh(repo, "checkout", "-q", "-b", "feature")
        res = pull_all.process_repo(repo, 30)
        self.assertEqual(res.status, pull_all.SKIPPED)
        self.assertIn("on 'feature', not 'main'", res.detail)

    def test_detached(self):
        bare, _ = self.make_remote()
        repo = self.clone(bare, "r")
        sh(repo, "checkout", "-q", "--detach")
        self.assertIn("detached", pull_all.process_repo(repo, 30).detail)

    def test_diverged_fails(self):
        bare, seed = self.make_remote()
        repo = self.clone(bare, "r")
        commit(repo, "local")
        commit(seed, "remote"); sh(seed, "push", "-q")
        res = pull_all.process_repo(repo, 30)
        self.assertEqual(res.status, pull_all.FAILED)

    def test_find_repos_skips_non_repos_and_hidden(self):
        bare, _ = self.make_remote()
        self.clone(bare, "r")
        (self.work / "plain").mkdir()
        (self.work / ".hidden").mkdir()
        sh(self.work / ".hidden", "init", "-q")
        (self.work / "file.txt").write_text("x")
        self.assertEqual([p.name for p in pull_all.find_repos(self.work)], ["r"])

    def test_cli_end_to_end(self):
        bare, seed = self.make_remote()
        self.clone(bare, "a"); self.clone(bare, "b")
        commit(seed, "b"); sh(seed, "push", "-q")
        (self.work / "b" / "a").write_text("dirty")
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "-j", "2", str(self.work)],
            capture_output=True, text=True,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("+1 commit", p.stdout)
        self.assertIn("unable to pull: working tree not clean", p.stdout)


if __name__ == "__main__":
    unittest.main()
