"""
Tests for open_codex/tools/file_tools.py
"""
import os
import pytest
from open_codex.tools import file_tools


# ── _safe_path ────────────────────────────────────────────────────────────────

class TestSafePath:
    def test_valid_relative_path(self, tmp_project):
        result = file_tools._safe_path("main.py", tmp_project)
        assert result == os.path.realpath(os.path.join(tmp_project, "main.py"))

    def test_valid_absolute_path_inside_project(self, tmp_project):
        abs_path = os.path.join(tmp_project, "main.py")
        result = file_tools._safe_path(abs_path, tmp_project)
        assert result == os.path.realpath(abs_path)

    def test_directory_traversal_blocked(self, tmp_project):
        result = file_tools._safe_path("../../etc/passwd", tmp_project)
        assert result is None

    def test_absolute_path_outside_project_blocked(self, tmp_project):
        result = file_tools._safe_path("/etc/passwd", tmp_project)
        assert result is None

    def test_empty_path_returns_none(self, tmp_project):
        assert file_tools._safe_path("", tmp_project) is None


# ── read_file ─────────────────────────────────────────────────────────────────

class TestReadFile:
    def test_reads_existing_file(self, tmp_project):
        content = file_tools.read_file("main.py", tmp_project)
        assert "print" in content

    def test_missing_file_returns_error(self, tmp_project):
        result = file_tools.read_file("nonexistent.py", tmp_project)
        assert result.startswith("ERROR")

    def test_traversal_returns_error(self, tmp_project):
        result = file_tools.read_file("../../etc/passwd", tmp_project)
        assert result.startswith("ERROR")

    def test_large_file_returns_error(self, tmp_project, monkeypatch):
        monkeypatch.setattr(file_tools, "MAX_FILE_SIZE", 5)
        path = os.path.join(tmp_project, "big.py")
        with open(path, "w") as f:
            f.write("x" * 100)
        result = file_tools.read_file("big.py", tmp_project)
        assert "too large" in result.lower()


# ── write_file ────────────────────────────────────────────────────────────────

class TestWriteFile:
    def test_writes_new_file(self, tmp_project):
        result = file_tools.write_file("new.py", "# new\n", tmp_project)
        assert result.startswith("OK")
        assert os.path.exists(os.path.join(tmp_project, "new.py"))

    def test_overwrites_existing_file(self, tmp_project):
        file_tools.write_file("main.py", "# replaced\n", tmp_project)
        content = file_tools.read_file("main.py", tmp_project)
        assert "replaced" in content

    def test_creates_nested_dirs(self, tmp_project):
        result = file_tools.write_file("sub/dir/file.py", "x", tmp_project)
        assert result.startswith("OK")
        assert os.path.exists(os.path.join(tmp_project, "sub", "dir", "file.py"))

    def test_traversal_blocked(self, tmp_project):
        result = file_tools.write_file("../../evil.py", "evil", tmp_project)
        assert result.startswith("ERROR")

    def test_reports_line_count(self, tmp_project):
        result = file_tools.write_file("lines.py", "a\nb\nc\n", tmp_project)
        # "a\nb\nc\n" has 3 newlines → count('\n')+1 = 4 lines
        assert "4 lines" in result


# ── list_directory ────────────────────────────────────────────────────────────

class TestListDirectory:
    def test_lists_project_root(self, tmp_project):
        result = file_tools.list_directory(".", tmp_project)
        assert "main.py" in result
        assert "README.md" in result

    def test_invalid_dir_returns_error(self, tmp_project):
        result = file_tools.list_directory("nonexistent/", tmp_project)
        assert result.startswith("ERROR")

    def test_ignores_pycache(self, tmp_project):
        pycache = os.path.join(tmp_project, "__pycache__")
        os.makedirs(pycache)
        result = file_tools.list_directory(".", tmp_project)
        assert "__pycache__" not in result

    def test_shows_dir_marker(self, tmp_project):
        os.makedirs(os.path.join(tmp_project, "mypackage"))
        result = file_tools.list_directory(".", tmp_project)
        assert "[DIR]" in result


# ── search_files ──────────────────────────────────────────────────────────────

class TestSearchFiles:
    def test_finds_match(self, tmp_project):
        result = file_tools.search_files("print", tmp_project)
        assert "main.py" in result

    def test_no_match_message(self, tmp_project):
        result = file_tools.search_files("xyzzy_nothere", tmp_project)
        assert "No matches" in result

    def test_case_insensitive(self, tmp_project):
        result = file_tools.search_files("PRINT", tmp_project)
        assert "main.py" in result

    def test_invalid_path_returns_error(self, tmp_project):
        result = file_tools.search_files("foo", tmp_project, "../../outside")
        assert result.startswith("ERROR")


# ── get_file_tree ─────────────────────────────────────────────────────────────

class TestGetFileTree:
    def test_returns_list(self, tmp_project):
        tree = file_tools.get_file_tree(tmp_project)
        assert isinstance(tree, list)
        assert len(tree) > 0

    def test_contains_main_py(self, tmp_project):
        tree = file_tools.get_file_tree(tmp_project)
        names = [e["name"] for e in tree]
        assert "main.py" in names

    def test_dirs_have_children(self, tmp_project):
        os.makedirs(os.path.join(tmp_project, "subdir"))
        (open(os.path.join(tmp_project, "subdir", "inner.py"), "w")
         .write("pass"))
        tree = file_tools.get_file_tree(tmp_project)
        dirs = [e for e in tree if e["type"] == "dir"]
        assert any(d["name"] == "subdir" for d in dirs)

    def test_max_depth_respected(self, tmp_project):
        deep = os.path.join(tmp_project, "a", "b", "c", "d", "e", "f")
        os.makedirs(deep)
        tree = file_tools.get_file_tree(tmp_project, max_depth=2)
        # Should not recurse 6 levels deep
        def max_depth_found(entries, depth=0):
            if not entries:
                return depth
            return max(max_depth_found(e.get("children", []), depth + 1)
                       for e in entries)
        assert max_depth_found(tree) <= 3  # some slack for fixture files
