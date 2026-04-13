"""
Shared fixtures for open-codex tests.
"""
import os
import json
import tempfile
import pytest


@pytest.fixture
def tmp_project(tmp_path):
    """Return a temporary directory that looks like a lightweight project."""
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "README.md").write_text("# Test Project\n")
    return str(tmp_path)


@pytest.fixture
def tmp_git_project(tmp_path):
    """Return a temporary git-initialised project directory."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "main.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    return str(tmp_path)


@pytest.fixture
def projects_file(tmp_path, monkeypatch):
    """Redirect DATA_DIR so API tests never touch ~/.open_codex."""
    data_dir = str(tmp_path / "open_codex_data")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    import open_codex.api as api_mod
    monkeypatch.setattr(api_mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(api_mod, "PROJECTS_FILE",
                        os.path.join(data_dir, "projects.json"))
    monkeypatch.setattr(api_mod, "THREADS_DIR",
                        os.path.join(data_dir, "threads"))
    os.makedirs(os.path.join(data_dir, "threads"), exist_ok=True)
    return data_dir
