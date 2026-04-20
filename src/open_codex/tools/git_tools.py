import subprocess
import os


def _git(args: list, cwd: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ['git'] + args, cwd=cwd,
            capture_output=True, text=True, timeout=15
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, '', 'git not found'
    except subprocess.TimeoutExpired:
        return -1, '', 'git command timed out'
    except Exception as e:
        return -1, '', str(e)


def is_git_repo(project_dir: str) -> bool:
    code, _, _ = _git(['rev-parse', '--git-dir'], project_dir)
    return code == 0


def get_status(project_dir: str) -> dict:
    if not is_git_repo(project_dir):
        return {"is_repo": False, "branch": None, "files": []}

    _, branch, _ = _git(['branch', '--show-current'], project_dir)
    branch = branch.strip() or 'HEAD'

    _, out, _ = _git(['status', '--porcelain=v1'], project_dir)
    files = []
    for line in out.splitlines():
        if len(line) >= 3:
            files.append({"status": line[:2].strip(), "path": line[3:]})

    return {"is_repo": True, "branch": branch, "files": files}


def get_diff(project_dir: str, staged: bool = False) -> str:
    args = ['diff']
    if staged:
        args.append('--staged')
    _, out, _ = _git(args, project_dir)
    return out.strip() or "(no unstaged changes)"


def get_diff_stats(project_dir: str) -> dict:
    """Return added/removed line counts for all uncommitted changes (staged + unstaged)."""
    added, removed = 0, 0
    for flag in ([], ['--staged']):
        _, out, _ = _git(['diff', '--numstat'] + flag, project_dir)
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2:
                try:
                    added += int(parts[0])
                except ValueError:
                    pass
                try:
                    removed += int(parts[1])
                except ValueError:
                    pass
    return {"added": added, "removed": removed}


def commit(project_dir: str, message: str) -> dict:
    code, _, err = _git(['add', '-A'], project_dir)
    if code != 0:
        return {"success": False, "error": err}
    code, out, err = _git(['commit', '-m', message], project_dir)
    if code != 0:
        return {"success": False, "error": err or out}
    _, h, _ = _git(['rev-parse', '--short', 'HEAD'], project_dir)
    return {"success": True, "hash": h.strip(), "output": out.strip()}


def push(project_dir: str, remote: str = 'origin', branch: str = '') -> dict:
    args = ['push', remote]
    if branch:
        args.append(branch)
    code, out, err = _git(args, project_dir)
    output = out.strip() or err.strip()
    return {'success': code == 0, 'output': output}


def pull(project_dir: str, remote: str = 'origin') -> dict:
    code, out, err = _git(['pull', remote], project_dir)
    output = out.strip() or err.strip()
    return {'success': code == 0, 'output': output}


def get_branches(project_dir: str) -> dict:
    _, out, _ = _git(['branch', '-a', '--format=%(refname:short)'], project_dir)
    _, current, _ = _git(['branch', '--show-current'], project_dir)
    return {
        "branches": [b for b in out.splitlines() if b.strip()],
        "current": current.strip(),
    }


def get_log(project_dir: str, n: int = 15) -> list:
    _, out, _ = _git(
        ['log', f'-{n}', '--format=%H%x1f%s%x1f%an%x1f%ar', '--no-merges'],
        project_dir
    )
    commits = []
    for line in out.splitlines():
        parts = line.split('\x1f')
        if len(parts) >= 4:
            commits.append({
                "hash": parts[0][:7],
                "subject": parts[1],
                "author": parts[2],
                "relative": parts[3],
            })
    return commits
