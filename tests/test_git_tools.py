"""
Tests for open_codex/tools/git_tools.py
"""
import os
import subprocess
import pytest
from open_codex.tools import git_tools


# ── is_git_repo ───────────────────────────────────────────────────────────────

class TestIsGitRepo:
    def test_true_in_git_repo(self, tmp_git_project):
        assert git_tools.is_git_repo(tmp_git_project) is True

    def test_false_in_plain_dir(self, tmp_project):
        assert git_tools.is_git_repo(tmp_project) is False


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_not_a_repo(self, tmp_project):
        status = git_tools.get_status(tmp_project)
        assert status["is_repo"] is False
        assert status["branch"] is None
        assert status["files"] == []

    def test_clean_repo(self, tmp_git_project):
        status = git_tools.get_status(tmp_git_project)
        assert status["is_repo"] is True
        assert status["branch"]  # non-empty string
        assert isinstance(status["files"], list)

    def test_dirty_repo_shows_new_file(self, tmp_git_project):
        (open(os.path.join(tmp_git_project, "new.py"), "w")).write("x = 1")
        status = git_tools.get_status(tmp_git_project)
        paths = [f["path"] for f in status["files"]]
        assert "new.py" in paths


# ── get_diff ─────────────────────────────────────────────────────────────────

class TestGetDiff:
    def test_no_changes(self, tmp_git_project):
        result = git_tools.get_diff(tmp_git_project)
        assert "no unstaged" in result.lower()

    def test_detects_modification(self, tmp_git_project):
        path = os.path.join(tmp_git_project, "main.py")
        with open(path, "w") as f:
            f.write("print('changed')\n")
        diff = git_tools.get_diff(tmp_git_project)
        assert "main.py" in diff or "changed" in diff


# ── get_diff_stats ────────────────────────────────────────────────────────────

class TestGetDiffStats:
    def test_returns_dict_with_keys(self, tmp_git_project):
        stats = git_tools.get_diff_stats(tmp_git_project)
        assert "added" in stats
        assert "removed" in stats

    def test_counts_additions(self, tmp_git_project):
        path = os.path.join(tmp_git_project, "extra.py")
        with open(path, "w") as f:
            f.write("a = 1\nb = 2\nc = 3\n")
        import subprocess
        subprocess.run(["git", "add", path], cwd=tmp_git_project,
                      capture_output=True)
        stats = git_tools.get_diff_stats(tmp_git_project)
        assert stats["added"] >= 3


# ── commit ────────────────────────────────────────────────────────────────────

class TestCommit:
    def test_commit_new_file(self, tmp_git_project):
        path = os.path.join(tmp_git_project, "feature.py")
        with open(path, "w") as f:
            f.write("pass\n")
        result = git_tools.commit(tmp_git_project, "add feature")
        assert result["success"] is True
        assert result["hash"]

    def test_commit_nothing_fails_gracefully(self, tmp_git_project):
        result = git_tools.commit(tmp_git_project, "empty commit")
        # Nothing to commit → git exits non-zero
        assert isinstance(result, dict)
        assert "success" in result


# ── get_branches ──────────────────────────────────────────────────────────────

class TestGetBranches:
    def test_returns_current_branch(self, tmp_git_project):
        info = git_tools.get_branches(tmp_git_project)
        assert info["current"]  # non-empty
        assert info["current"] in info["branches"]


# ── get_log ───────────────────────────────────────────────────────────────────

class TestGetLog:
    def test_log_has_initial_commit(self, tmp_git_project):
        commits = git_tools.get_log(tmp_git_project, n=5)
        assert len(commits) >= 1
        first = commits[0]
        assert "hash" in first
        assert "subject" in first
        assert "author" in first
        assert "relative" in first

    def test_log_limit_respected(self, tmp_git_project):
        # Add a few more commits
        for i in range(3):
            p = os.path.join(tmp_git_project, f"f{i}.py")
            open(p, "w").write(f"x={i}")
            subprocess.run(["git", "add", "."], cwd=tmp_git_project,
                           capture_output=True)
            subprocess.run(["git", "commit", "-m", f"commit {i}"],
                           cwd=tmp_git_project, capture_output=True)
        commits = git_tools.get_log(tmp_git_project, n=2)
        assert len(commits) == 2
