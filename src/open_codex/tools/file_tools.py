import os

IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env',
    'dist', 'build', '.next', '.nuxt', 'coverage', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', 'target', 'out', '.DS_Store',
}
IGNORE_EXTENSIONS = {'.pyc', '.pyo', '.class', '.o', '.so', '.dylib', '.dll', '.exe', '.whl'}
MAX_FILE_SIZE = 200_000  # 200KB


def _safe_path(path: str, project_dir: str) -> str | None:
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(project_dir, path)
    real = os.path.realpath(os.path.abspath(full))
    project_real = os.path.realpath(os.path.abspath(project_dir))
    if not (real == project_real or real.startswith(project_real + os.sep)):
        return None
    return real


def read_file(path: str, project_dir: str) -> str:
    safe = _safe_path(path, project_dir)
    if not safe:
        return f"ERROR: Invalid path: {path}"
    if not os.path.isfile(safe):
        return f"ERROR: File not found: {path}"
    size = os.path.getsize(safe)
    if size > MAX_FILE_SIZE:
        return f"ERROR: File too large ({size} bytes). Use search_files to find specific content."
    try:
        with open(safe, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {e}"


def write_file(path: str, content: str, project_dir: str) -> str:
    safe = _safe_path(path, project_dir)
    if not safe:
        return f"ERROR: Invalid path: {path}"
    try:
        parent = os.path.dirname(safe)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(safe, 'w', encoding='utf-8') as f:
            f.write(content)
        rel = os.path.relpath(safe, project_dir)
        lines = content.count('\n') + 1
        return f"OK: Wrote {lines} lines to {rel}"
    except Exception as e:
        return f"ERROR: {e}"


def edit_file(path: str, old_string: str, new_string: str, project_dir: str, replace_all: bool = False) -> str:
    safe = _safe_path(path, project_dir)
    if not safe:
        return f"ERROR: Invalid path: {path}"
    if not os.path.isfile(safe):
        return f"ERROR: File not found: {path}"
    try:
        with open(safe, 'r', encoding='utf-8', errors='replace') as f:
            original = f.read()
    except Exception as e:
        return f"ERROR: {e}"

    if old_string not in original:
        # Give a useful hint: show nearby content so the model can correct its old_string
        lines = original.splitlines()
        hint_lines = lines[:5]
        return (
            f"ERROR: old_string not found in {path}. "
            f"File starts with:\n" + "\n".join(hint_lines) +
            ("\n..." if len(lines) > 5 else "")
        )

    count = original.count(old_string)
    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string appears {count} times in {path}. "
            "Add more surrounding context to make it unique, or set replace_all=true."
        )

    updated = original.replace(old_string, new_string) if replace_all else original.replace(old_string, new_string, 1)
    try:
        with open(safe, 'w', encoding='utf-8') as f:
            f.write(updated)
        rel = os.path.relpath(safe, project_dir)
        replacements = count if replace_all else 1
        return f"OK: Patched {replacements} occurrence(s) in {rel}"
    except Exception as e:
        return f"ERROR: {e}"


def list_directory(path: str, project_dir: str) -> str:
    target = project_dir if path in ('.', '') else _safe_path(path, project_dir)
    if not target:
        return f"ERROR: Invalid path: {path}"
    if not os.path.isdir(target):
        return f"ERROR: Not a directory: {path}"
    try:
        lines = []
        for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name in IGNORE_DIRS:
                continue
            if entry.name.startswith('.') and entry.name not in ('.env', '.gitignore', '.gitattributes', '.editorconfig'):
                continue
            if entry.is_dir():
                lines.append(f"[DIR]  {entry.name}/")
            else:
                ext = os.path.splitext(entry.name)[1]
                if ext not in IGNORE_EXTENSIONS:
                    size = entry.stat().st_size
                    lines.append(f"[FILE] {entry.name}  ({size:,} bytes)")
        rel = os.path.relpath(target, project_dir) if target != project_dir else '.'
        header = f"Directory listing of {rel}/:"
        return header + "\n" + ("\n".join(lines) or "  (empty)")
    except Exception as e:
        return f"ERROR: {e}"


def search_files(query: str, project_dir: str, path: str = ".") -> str:
    target = project_dir if path in ('.', '') else _safe_path(path, project_dir)
    if not target:
        return "ERROR: Invalid search path"

    results = []
    MAX_RESULTS = 40

    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
        for filename in files:
            ext = os.path.splitext(filename)[1]
            if ext in IGNORE_EXTENSIONS:
                continue
            filepath = os.path.join(root, filename)
            rel = os.path.relpath(filepath, project_dir)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    for i, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(results) >= MAX_RESULTS:
                                break
            except Exception:
                continue
            if len(results) >= MAX_RESULTS:
                break

    if not results:
        return f"No matches found for '{query}'"
    suffix = f"\n(truncated at {MAX_RESULTS} results)" if len(results) == MAX_RESULTS else ""
    return f"Found {len(results)} match(es) for '{query}':\n" + "\n".join(results) + suffix


def get_file_tree(project_dir: str, max_depth: int = 5) -> list:
    def scan(path, depth):
        if depth > max_depth:
            return []
        entries = []
        try:
            for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
                if entry.name in IGNORE_DIRS:
                    continue
                if entry.name.startswith('.') and entry.name not in ('.env', '.gitignore'):
                    continue
                if entry.is_dir():
                    children = scan(entry.path, depth + 1)
                    entries.append({
                        "name": entry.name,
                        "type": "dir",
                        "path": os.path.relpath(entry.path, project_dir),
                        "children": children,
                    })
                else:
                    ext = os.path.splitext(entry.name)[1]
                    if ext not in IGNORE_EXTENSIONS:
                        entries.append({
                            "name": entry.name,
                            "type": "file",
                            "path": os.path.relpath(entry.path, project_dir),
                            "size": entry.stat().st_size,
                        })
        except PermissionError:
            pass
        return entries

    return scan(project_dir, 0)
