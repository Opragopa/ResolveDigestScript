"""Fast-forward an installed Git checkout; never reset or discard local work."""
import os
from pathlib import Path
import subprocess


def update_checkout(directory):
    root = Path(directory).resolve()
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True,
            encoding="utf-8", errors="replace", timeout=12, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()
    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
            return False, "Автообновление: папка не является отдельной Git-установкой."
        if git("branch", "--show-current") != "main":
            return False, "Автообновление пропущено: текущая ветка не main."
        remote = git("remote", "get-url", "origin").rstrip("/").removesuffix(".git")
        if remote not in ("https://github.com/Opragopa/ResolveDigestScript", "git@github.com:Opragopa/ResolveDigestScript"):
            return False, "Автообновление пропущено: origin отличается от ResolveDigestScript."
        if git("status", "--porcelain", "--untracked-files=normal"):
            return False, "Автообновление пропущено: в установке есть локальные изменения или новые файлы."
        before = git("rev-parse", "HEAD")
        git("fetch", "--quiet", "origin", "main")
        git("merge", "--ff-only", "--no-edit", "origin/main")
        after = git("rev-parse", "HEAD")
        return before != after, "Версия Resolve Digest: " + after[:7]
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return False, "Автообновление недоступно; используется установленная версия. " + str(error)
