"""Installation workspace: code, data root, private uv/Python and the run skill.

The host agent owns installation (ADR 0005).  This module makes the first
phase checkable instead of conversational:

    root/                         installation workspace (host project folder)
      .frontier/install.json      resolved code / data / interpreter / skill paths
      frontier/                   code checkout (never the data root)
      frontier-archive/           data root (never inside the code checkout)
        bin/uv(.exe)              private uv fallback, outside the code checkout
        .venv/                    private environment created and used by uv
      <host skills dir>/frontier-run/SKILL.md   small launcher, not a repo copy

Rules that the functions below keep:

- an existing checkout is inspected first and never overwritten or pulled when
  it has local changes or a different origin;
- uv is resolved from outside the workspace first (recorded or system uv), then
  a uv installed into the data root; nothing asks the user to edit PATH;
- the private environment and its interpreter live in the data root, never in
  the code checkout, and the absolute interpreter path is recorded in both the
  workspace pointer and the install configuration;
- no environment variable, PATH entry, registry value, service or OS task is
  written;
- a failed phase returns ``ok: false`` with an actionable reason and stays
  resumable: rerunning reuses everything already verified, and a broken
  interpreter is reported as blocked with the exact ``--clear`` repair command
  instead of being silently rebuilt.
"""

from __future__ import annotations

import io
import os
import platform as platform_mod
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

from common import ensure_dir, now, read_json, write_json
from hostrun.base import HostRunError, resolve_executable, update_config

SCHEMA_VERSION = 1
RECORD_REL = Path(".frontier") / "install.json"
DEFAULT_CODE_DIRNAME = "frontier"
DEFAULT_DATA_DIRNAME = "frontier-archive"
DEFAULT_REPO_URL = "https://github.com/Moke110/frontier.git"
DEFAULT_PYTHON = "3.13"
ENV_DIRNAME = ".venv"
SKILL_NAME = "frontier-run"
SKILL_ENTRY = Path("skills") / SKILL_NAME / "SKILL.md"
SKILL_REFERENCES = (
    Path("skills") / SKILL_NAME / "references" / "installation.md",
    Path("skills") / SKILL_NAME / "references" / "workflow.md",
)
REPO_FILES = (
    Path("common.py"),
    Path("requirements.txt"),
    Path("contracts") / "README.md",
    SKILL_ENTRY,
    *SKILL_REFERENCES,
)
UV_ASSETS = {
    ("Windows", "AMD64"): "uv-x86_64-pc-windows-msvc.zip",
    ("Windows", "ARM64"): "uv-aarch64-pc-windows-msvc.zip",
    ("Linux", "x86_64"): "uv-x86_64-unknown-linux-gnu.tar.gz",
    ("Linux", "aarch64"): "uv-aarch64-unknown-linux-gnu.tar.gz",
    ("Darwin", "x86_64"): "uv-x86_64-apple-darwin.tar.gz",
    ("Darwin", "arm64"): "uv-aarch64-apple-darwin.tar.gz",
}
UV_RELEASE = "https://github.com/astral-sh/uv/releases/latest/download/{asset}"


# ------------------------------------------------------------------ helpers
def _run(
    argv: list[str],
    *,
    runner=subprocess.run,
    timeout: int = 300,
    cwd: str | Path | None = None,
    env: dict | None = None,
) -> dict:
    """One bounded process call; never prints credentials or raw stdout."""
    kwargs = {"capture_output": True, "text": True, "timeout": timeout, "cwd": cwd}
    if env is not None:
        kwargs["env"] = env
    try:
        proc = runner(argv, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "code": None, "out": "", "err": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "out": (proc.stdout or "").strip(),
        "err": (proc.stderr or "").strip(),
    }


def _tail(text: str, limit: int = 400) -> str:
    text = " ".join((text or "").split())
    return text[-limit:]


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def environment_venv(home: str | Path) -> Path:
    """The private environment directory inside the data root."""
    return Path(home).expanduser().resolve() / ENV_DIRNAME


def environment_python(home: str | Path) -> Path:
    """The absolute interpreter path installation records and later reuses."""
    return _venv_python(environment_venv(home))


def repair_command(root: str | Path, home: str | Path) -> str:
    """The exact command that rebuilds a missing or broken interpreter."""
    return (
        f'"{sys.executable or "python"}" -m hostrun.cli '
        f'--home "{Path(home).expanduser().resolve()}" install toolchain '
        f'--root "{Path(root).expanduser().resolve()}" --clear'
    )


def normalize_url(url: str) -> str:
    text = str(url or "").strip().lower()
    if text.endswith(".git"):
        text = text[:-4]
    return text.rstrip("/")


def resolve_layout(
    root: str | Path,
    *,
    code_dirname: str = DEFAULT_CODE_DIRNAME,
    data_dirname: str = DEFAULT_DATA_DIRNAME,
) -> dict:
    """Resolve and validate the two independent directories under ``root``."""
    root_path = Path(root).expanduser().resolve()
    code = Path(code_dirname).expanduser()
    data = Path(data_dirname).expanduser()
    repo = (code if code.is_absolute() else root_path / code).resolve()
    home = (data if data.is_absolute() else root_path / data).resolve()
    if repo == home:
        raise HostRunError("代码目录与数据根不能是同一个目录")
    try:
        home.relative_to(repo)
    except ValueError:
        pass
    else:
        raise HostRunError("数据根不能放在代码目录内，否则升级会覆盖研究数据")
    return {"root": str(root_path), "repo": str(repo), "home": str(home)}


def record_path(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / RECORD_REL


def load_record(root: str | Path) -> dict:
    return read_json(record_path(root)) or {}


def save_record(root: str | Path, record: dict) -> Path:
    path = record_path(root)
    write_json(path, {**record, "schema_version": SCHEMA_VERSION, "updated_at": now()})
    return path


def locate(start: str | Path | None = None) -> dict:
    """Find the nearest workspace record, so a moved skill can still locate code."""
    current = Path(start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        record = load_record(directory)
        if record:
            return record
    return {}


# ------------------------------------------------------------- code checkout
def git_facts(repo: str | Path, *, runner=subprocess.run) -> dict:
    repo = Path(repo)
    status = _run(["git", "-C", str(repo), "status", "--porcelain"], runner=runner)
    if not status["ok"]:
        return {"ok": False, "error": _tail(status["err"] or status["out"]) or "git status failed"}
    origin = _run(["git", "-C", str(repo), "remote", "get-url", "origin"], runner=runner)
    commit = _run(["git", "-C", str(repo), "rev-parse", "HEAD"], runner=runner)
    return {
        "ok": True,
        "dirty": bool(status["out"].strip()),
        "dirty_files": [line[3:] for line in status["out"].splitlines() if line.strip()][:20],
        "origin": origin["out"] if origin["ok"] else "",
        "commit": commit["out"] if commit["ok"] else "",
    }


def inspect_checkout(repo: str | Path, *, repo_url: str = DEFAULT_REPO_URL, runner=subprocess.run) -> dict:
    """What is already at the code path — without changing a single byte."""
    repo = Path(repo)
    if not repo.exists():
        return {"state": "absent", "path": str(repo)}
    if not repo.is_dir():
        return {"state": "not_a_directory", "path": str(repo)}
    entries = list(repo.iterdir())
    if not entries:
        return {"state": "empty", "path": str(repo)}
    if not (repo / ".git").exists():
        return {"state": "not_a_git_repo", "path": str(repo), "entries": len(entries)}
    facts = git_facts(repo, runner=runner)
    if not facts["ok"]:
        return {"state": "git_error", "path": str(repo), "error": facts["error"]}
    if repo_url and normalize_url(facts["origin"]) != normalize_url(repo_url):
        return {"state": "other_origin", **facts, "path": str(repo)}
    if facts["dirty"]:
        return {"state": "dirty", **facts, "path": str(repo)}
    return {"state": "reusable", **facts, "path": str(repo)}


def _clone(url: str, repo: Path, *, runner=subprocess.run, timeout: int = 900) -> dict:
    ensure_dir(repo.parent)
    result = _run(
        ["git", "clone", "--depth", "1", url, str(repo)],
        runner=runner,
        timeout=timeout,
    )
    return {"ok": result["ok"], "error": _tail(result["err"] or result["out"]), "result": result}


def _clone_marker(root: Path) -> Path:
    return Path(root) / ".frontier" / "clone-in-progress.json"


def _write_clone_marker(root: Path, repo: Path) -> None:
    path = _clone_marker(root)
    ensure_dir(path.parent)
    write_json(path, {"repo": str(repo), "started_at": now()})


def _clear_clone_marker(root: Path) -> None:
    _clone_marker(root).unlink(missing_ok=True)


def _recover_partial_clone(root: Path, repo: Path) -> dict | None:
    """Move an interrupted clone aside and retry, never deleting user files.

    Only a checkout left by this installer (marker present) and broken enough
    that git cannot run is moved; the original bytes stay under a new name.
    """
    marker = _clone_marker(root)
    if not marker.exists():
        return None
    if not repo.exists():
        _clear_clone_marker(root)
        return None
    archived = repo.with_name(f"{repo.name}.incomplete-{int(time.time())}")
    try:
        repo.rename(archived)
    except OSError as exc:
        return {
            "blocked": (
                f"检测到上次中断的代码副本 {repo}，但无法移到 {archived}：{exc}；"
                "请手动移走后重试"
            ),
            "archived": str(archived),
        }
    _clear_clone_marker(root)
    return {"archived": str(archived)}


def _candidate_path(root_path: Path, dirname: str) -> Path:
    candidate = Path(dirname).expanduser()
    return (candidate if candidate.is_absolute() else root_path / candidate).resolve()


def acquire(
    root: str | Path,
    *,
    repo_url: str = DEFAULT_REPO_URL,
    code_dirname: str = DEFAULT_CODE_DIRNAME,
    data_dirname: str = DEFAULT_DATA_DIRNAME,
    dry_run: bool = False,
    runner=subprocess.run,
) -> dict:
    """Acquire code safely and create the data root; never overwrite user work.

    A data root that would sit inside the code checkout is refused before any
    directory is created, and the refusal carries the reason plus the offending
    candidate so the caller can report it instead of writing anywhere.
    """
    root_path = Path(root).expanduser().resolve()
    try:
        layout = resolve_layout(root, code_dirname=code_dirname, data_dirname=data_dirname)
    except HostRunError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "dry_run": dry_run,
            "action": "rejected",
            "layout_valid": False,
            "root": str(root_path),
            "repo": str(_candidate_path(root_path, code_dirname)),
            "home": str(_candidate_path(root_path, data_dirname)),
            "code_dirname": code_dirname,
            "data_dirname": data_dirname,
            "blocked": str(exc),
        }
    repo, home = Path(layout["repo"]), Path(layout["home"])
    existing = inspect_checkout(repo, repo_url=repo_url, runner=runner)
    recovered = None
    if existing["state"] in {"git_error", "not_a_git_repo"}:
        recovery = _recover_partial_clone(Path(layout["root"]), repo)
        if recovery and recovery.get("blocked"):
            return {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "dry_run": dry_run,
                "action": "blocked",
                "layout_valid": True,
                "root": layout["root"],
                "repo": layout["repo"],
                "home": layout["home"],
                "repo_url": repo_url,
                "blocked": recovery["blocked"],
            }
        if recovery:
            recovered = recovery
            existing = inspect_checkout(repo, repo_url=repo_url, runner=runner)

    blocked = None
    if existing["state"] in {"absent", "empty"}:
        action = "clone"
        if not dry_run:
            _write_clone_marker(Path(layout["root"]), repo)
            clone = _clone(repo_url, repo, runner=runner)
            if not clone["ok"]:
                blocked = f"代码获取失败：{clone['error'] or 'git clone 退出非零'}；重跑会移开不完整副本后重试"
                action = "clone_failed"
            else:
                _clear_clone_marker(Path(layout["root"]))
    elif existing["state"] == "reusable":
        action = "reuse"
    elif existing["state"] == "dirty":
        action = "blocked"
        blocked = (
            "已有代码副本存在未提交改动，未拉取或覆盖；请先提交/备份，"
            "或改用另一个工作区"
        )
    elif existing["state"] == "other_origin":
        action = "blocked"
        blocked = f"已有代码副本的 origin 是 {existing.get('origin') or '<空>'}，与 {repo_url} 不符"
    elif existing["state"] == "not_a_git_repo":
        action = "blocked"
        blocked = "代码目录已存在但不是 git 仓库；未覆盖，请改用空工作区或自行移走"
    else:
        action = "blocked"
        blocked = f"无法检查已有代码副本：{existing.get('error') or existing['state']}"

    data_created = False
    data_entries = 0
    if home.exists():
        data_entries = len(list(home.iterdir())) if home.is_dir() else 0
    elif not dry_run:
        ensure_dir(home)
        data_created = True
    elif dry_run:
        data_created = True

    facts = {}
    if not dry_run and (repo / ".git").exists():
        facts = git_facts(repo, runner=runner)

    result = {
        "schema_version": SCHEMA_VERSION,
        "ok": blocked is None,
        "dry_run": dry_run,
        "action": action,
        "layout_valid": True,
        "root": layout["root"],
        "repo": layout["repo"],
        "home": layout["home"],
        "repo_url": repo_url,
        "origin": facts.get("origin", ""),
        "commit": facts.get("commit", ""),
        "dirty": bool(facts.get("dirty")),
        "data_root_created": data_created,
        "data_root_entries": data_entries,
        "recovered_partial_clone": recovered,
        "existing": {k: v for k, v in existing.items() if k != "dirty_files"},
    }
    if blocked:
        result["blocked"] = blocked
        return result

    if not dry_run and facts:
        record = {
            **{k: result[k] for k in ("root", "repo", "home", "repo_url", "origin", "commit")},
            "code_dirname": code_dirname,
            "data_dirname": data_dirname,
        }
        previous = load_record(root)
        save_record(root, {**previous, **record})
    return result


# ------------------------------------------------------------------ toolchain
def uv_asset(platform_name: str | None = None, machine: str | None = None) -> str:
    name = platform_name or platform_mod.system()
    arch = machine or platform_mod.machine()
    if (name, arch) not in UV_ASSETS:
        raise HostRunError(f"没有适用于 {name}/{arch} 的 uv 安装包映射")
    return UV_ASSETS[(name, arch)]


def _extract_uv(blob: bytes, asset: str, target_dir: Path) -> Path:
    ensure_dir(target_dir)
    binary = "uv.exe" if asset.endswith(".zip") else "uv"
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            member = next((n for n in archive.namelist() if n.endswith(binary)), None)
            if not member:
                raise HostRunError("uv 安装包中找不到可执行文件")
            data = archive.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            member = next((m for m in archive.getmembers() if m.name.endswith("/" + binary) or m.name == binary), None)
            if not member:
                raise HostRunError("uv 安装包中找不到可执行文件")
            data = archive.extractfile(member).read()
    path = target_dir / binary
    path.write_bytes(data)
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _private_uv_path(home: Path) -> Path:
    return Path(home).expanduser().resolve() / "bin" / ("uv.exe" if os.name == "nt" else "uv")


def install_uv(
    home: str | Path,
    *,
    asset: str | None = None,
    fetch=None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> dict:
    """Install uv privately under ``<home>/bin`` (no PATH write)."""
    asset = asset or uv_asset(platform_name, machine)
    target_dir = Path(home).expanduser().resolve() / "bin"
    url = UV_RELEASE.format(asset=asset)
    if fetch is None:
        import urllib.request

        def fetch(address: str) -> bytes:  # pragma: no cover - network path
            with urllib.request.urlopen(address, timeout=120) as response:
                return response.read()

    try:
        blob = fetch(url)
        path = _extract_uv(blob, asset, target_dir)
    except HostRunError as exc:
        return {"ok": False, "reason": "uv_install_failed", "error": str(exc), "url": url}
    except Exception as exc:  # noqa: BLE001 - download/extract failures are results
        return {"ok": False, "reason": "uv_install_failed", "error": _tail(str(exc)), "url": url}
    return {"ok": True, "path": str(path), "source": "private", "url": url}


def ensure_uv(
    home: str | Path,
    *,
    uv_path: str | None = None,
    recorded: str | None = None,
    fetch=None,
    runner=subprocess.run,
    platform_name: str | None = None,
    machine: str | None = None,
) -> dict:
    """Resolve uv from outside the workspace first, then the data-root private copy.

    Order: explicit ``--uv``, the recorded uv, a read-only PATH lookup, then
    ``<home>/bin``; only when none is usable is uv downloaded into the data
    root. A candidate that cannot even answer ``--version`` is skipped, so one
    stale recorded path cannot mask a working system uv.
    """
    home_path = Path(home).expanduser().resolve()
    private = _private_uv_path(home_path)
    candidates: list[tuple[str, str]] = []
    if uv_path:
        found = resolve_executable(uv_path)
        if not found["found"]:
            return {
                "ok": False,
                "status": "blocked",
                "note": f"指定的 uv 不存在：{uv_path}；请给出 uv 可执行文件的绝对路径或省略 --uv",
                "evidence": {"source": "explicit", "path": str(uv_path)},
            }
        candidates.append(("explicit", found["path"]))
    else:
        if recorded and Path(recorded).expanduser().is_file():
            candidates.append(("recorded", str(Path(recorded).expanduser())))
        system = resolve_executable(None, names=["uv", "uv.exe"])
        if system["found"]:
            candidates.append((system["source"], system["path"]))
    if private.is_file():
        candidates.append(("private", str(private)))

    for source, path in candidates:
        version = _run([path, "--version"], runner=runner, timeout=60)
        if version["ok"]:
            return {
                "ok": True,
                "status": "ok",
                "path": path,
                "source": source,
                "version": version["out"].splitlines()[0] if version["out"] else "",
                "installed": None,
            }
    if uv_path:
        return {
            "ok": False,
            "status": "blocked",
            "note": f"指定的 uv 无法运行：{uv_path}；请修复该可执行文件或改用系统 uv",
            "evidence": {"source": "explicit", "path": str(uv_path)},
        }

    installed = install_uv(
        home_path, fetch=fetch, platform_name=platform_name, machine=machine
    )
    if not installed["ok"]:
        return {
            "ok": False,
            "status": "blocked",
            "note": "未找到 uv，数据根私有安装也失败：" + installed["error"],
            "evidence": {"source": "missing", "install": installed},
        }
    version = _run([installed["path"], "--version"], runner=runner, timeout=60)
    return {
        "ok": True,
        "status": "ok",
        "path": installed["path"],
        "source": "private",
        "version": version["out"].splitlines()[0] if version["ok"] and version["out"] else "",
        "installed": installed,
    }


def check_runtime(python_path: str | Path, *, runner=subprocess.run) -> dict:
    """The installed interpreter must already import what installation needs."""
    probe = _run(
        [str(python_path), "-c", "import yaml, fitz"],
        runner=runner,
        timeout=120,
    )
    return {
        "ok": probe["ok"],
        "error": _tail(probe["err"] or probe["out"]),
        "python": str(python_path),
    }


def ensure_environment(
    repo: str | Path,
    home: str | Path,
    *,
    uv: str,
    python_version: str = DEFAULT_PYTHON,
    runner=subprocess.run,
    verify=None,
    clear: bool = False,
    repair: str = "",
    expected: str | Path | None = None,
) -> dict:
    """Create the private environment in ``<home>/.venv``, then verify imports.

    An environment recorded by an earlier run that no longer passes the import
    probe — or whose recorded interpreter disappeared — is *not* rebuilt
    silently: the call returns ``blocked`` with the repair command unless the
    caller explicitly asked for ``clear=True``.
    """
    repo = Path(repo)
    home = Path(home).expanduser().resolve()
    venv = environment_venv(home)
    python = _venv_python(venv)
    verify = verify or (lambda path: check_runtime(path, runner=runner))
    requirements = repo / "requirements.txt"

    existing_ok = python.is_file() and verify(python).get("ok")
    if existing_ok:
        return {
            "ok": True,
            "status": "ok",
            "python": str(python),
            "venv": str(venv),
            "uv": str(uv),
            "created": False,
            "repaired": False,
            "probe": {"ok": True, "error": ""},
            "note": "已有数据根私有环境通过依赖自检",
        }

    recorded_missing = bool(expected) and Path(expected) == python
    broken = venv.exists() or python.exists() or recorded_missing
    if broken and not clear:
        hint = repair or "以 --clear 重跑 install toolchain"
        reason = "interpreter_missing" if recorded_missing and not python.exists() else "interpreter_broken"
        return {
            "ok": False,
            "status": "blocked",
            "reason": reason,
            "python": str(python),
            "venv": str(venv),
            "uv": str(uv),
            "created": False,
            "repaired": False,
            "probe": {"ok": False, "error": ""},
            "note": f"数据根私有解释器不可用：{python}；修复：{hint}",
        }

    ensure_dir(home)
    repaired = broken
    child_env = {
        **os.environ,
        "UV_PYTHON_INSTALL_DIR": str(home / "python"),
        "UV_CACHE_DIR": str(home / "uv-cache"),
        "UV_LINK_MODE": "copy",
    }
    create = [str(uv), "venv", "--python", str(python_version), str(venv)]
    if repaired:
        create.insert(4, "--clear")
    made = _run(create, runner=runner, timeout=900, cwd=str(repo), env=child_env)
    if not made["ok"]:
        return {
            "ok": False,
            "status": "blocked",
            "note": "创建私有环境失败：" + (_tail(made["err"] or made["out"]) or "uv venv 退出非零"),
            "python": str(python),
            "venv": str(venv),
            "uv": str(uv),
            "repaired": repaired,
        }
    if not requirements.exists():
        return {
            "ok": False,
            "status": "blocked",
            "note": f"缺少依赖声明：{requirements}",
            "python": str(python),
            "venv": str(venv),
            "uv": str(uv),
        }
    installed = _run(
        [
            str(uv),
            "pip",
            "install",
            "--python",
            str(python),
            "-r",
            str(requirements),
        ],
        runner=runner,
        timeout=1800,
        cwd=str(repo),
        env=child_env,
    )
    if not installed["ok"]:
        return {
            "ok": False,
            "status": "blocked",
            "note": "安装依赖失败：" + (_tail(installed["err"] or installed["out"]) or "uv pip install 退出非零"),
            "python": str(python),
            "venv": str(venv),
            "uv": str(uv),
            "repaired": repaired,
        }
    checked = verify(python)
    ok = bool(checked.get("ok"))
    note = "" if ok else "依赖装好后仍无法导入 yaml/fitz：" + checked.get("error", "")
    if not ok and repair:
        note += f"；修复：{repair}"
    return {
        "ok": ok,
        "status": "ok" if ok else "blocked",
        "python": str(python),
        "venv": str(venv),
        "uv": str(uv),
        "created": not repaired,
        "repaired": repaired,
        "probe": {"ok": ok, "error": "" if ok else checked.get("error", "")},
        "note": note,
    }


def toolchain(
    root: str | Path,
    *,
    uv_path: str | None = None,
    python_version: str = DEFAULT_PYTHON,
    fetch=None,
    runner=subprocess.run,
    clear: bool = False,
) -> dict:
    """Resolve uv outside the workspace, then build the data-root environment."""
    root_path = Path(root).expanduser().resolve()
    record = load_record(root_path)
    if not record.get("repo") or not record.get("home"):
        raise HostRunError("先执行 install workspace，工作区尚未记录代码与数据目录")
    repo = Path(record["repo"])
    home = Path(record["home"])
    repair = repair_command(root_path, home)
    uv = ensure_uv(
        home,
        uv_path=uv_path,
        recorded=record.get("uv"),
        fetch=fetch,
        runner=runner,
    )
    if not uv["ok"]:
        return {
            "ok": False,
            "status": "blocked",
            "uv": uv,
            "note": uv["note"],
            "repair": repair,
        }
    env = ensure_environment(
        repo,
        home,
        uv=uv["path"],
        python_version=python_version,
        runner=runner,
        clear=clear,
        repair=repair,
        expected=record.get("python"),
    )
    result = {
        "ok": env["ok"],
        "status": env["status"],
        "uv": uv,
        "environment": env,
        "repair": repair,
    }
    if not env["ok"]:
        result["note"] = env["note"]
        return result
    save_record(
        root_path,
        {
            **record,
            "uv": uv["path"],
            "uv_source": uv["source"],
            "uv_version": uv.get("version", ""),
            "python": env["python"],
            "python_version": python_version,
            "venv": env["venv"],
            "environment": {
                "created": env.get("created", False),
                "repaired": env.get("repaired", False),
                "imports_ok": bool(env.get("probe", {}).get("ok")),
                "checked_at": now(),
            },
        },
    )
    update_config(
        home,
        paths={
            "uv": uv["path"],
            "python": env["python"],
            "venv": env["venv"],
        },
    )
    result["note"] = env["note"]
    return result


# ---------------------------------------------------------------------- skill
def _launcher_text(record: dict) -> str:
    return f"""---
name: {SKILL_NAME}
description: "Install, run, pause or recover frontier on this host. Read the repository entry and references before acting."
---

# {SKILL_NAME}

本文件是安装时生成的**入口指针**，不是仓库副本。运行与安装规则以仓库内文件为准。

- 仓库：{record["repo"]}
- 数据根：{record["home"]}
- 解释器：{record.get("python") or "<由 install toolchain 记录>"}
- 安装记录：{Path(record["root"]) / RECORD_REL}

## 每次唤醒

1. 读取 `{Path(record["repo"]) / SKILL_ENTRY}`。
2. 读取它引用的 `references/installation.md` 与 `references/workflow.md`。
3. 以仓库根为工作目录，用上面记录的解释器执行 `python -m hostrun.cli ...`。
4. 不要根据本文件所在位置推断仓库；路径变化时重新运行 `install skill`。

本文件不含凭据，也不修改环境变量、PATH 或注册表。
"""


def register_skill(
    root: str | Path,
    target: str | Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Write a small launcher skill that points at the real repository."""
    record = load_record(root)
    if not record.get("repo") or not record.get("home"):
        raise HostRunError("先执行 install workspace，工作区尚未记录代码与数据目录")
    target_dir = Path(target).expanduser().resolve()
    launcher = target_dir / "SKILL.md"
    entry = Path(record["repo"]) / SKILL_ENTRY
    references = [Path(record["repo"]) / rel for rel in SKILL_REFERENCES]
    missing = [str(path) for path in [entry, *references] if not path.is_file()]
    if missing:
        return {
            "ok": False,
            "status": "blocked",
            "reason": "repo_missing_skill_files",
            "missing": missing,
            "note": "仓库缺少运行技能或参考文件；先更新代码副本",
        }
    if target_dir == entry.parent:
        raise HostRunError("目标目录就是技能源目录；请注册到宿主的技能目录，不要覆盖仓库文件")
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "skill": str(launcher),
            "target": str(target_dir),
            "entry": str(entry),
            "references": [str(path) for path in references],
        }
    ensure_dir(target_dir)
    launcher.write_text(_launcher_text(record), encoding="utf-8")
    record = {**record, "skill": str(launcher), "skill_target": str(target_dir)}
    save_record(root, record)
    return {
        "ok": True,
        "skill": str(launcher),
        "target": str(target_dir),
        "entry": str(entry),
        "references": [str(path) for path in references],
        "registered": True,
    }


def verify_skill(record: dict) -> dict:
    """The launcher, the entry and every reference must be readable now."""
    launcher = Path(record.get("skill") or "")
    entry = Path(record.get("repo") or "") / SKILL_ENTRY
    references = [Path(record.get("repo") or "") / rel for rel in SKILL_REFERENCES]
    problems = []
    if not launcher.is_file():
        problems.append(f"缺少入口指针：{launcher}")
    else:
        text = launcher.read_text(encoding="utf-8", errors="replace")
        if record.get("repo") and record["repo"] not in text:
            problems.append("入口指针未指向记录的仓库")
    for path in [entry, *references]:
        if not path.is_file():
            problems.append(f"缺少参考文件：{path}")
    return {
        "ok": not problems,
        "skill": str(launcher),
        "entry": str(entry),
        "references": [str(path) for path in references],
        "problems": problems,
    }


# --------------------------------------------------------------------- status
def status(root: str | Path) -> dict:
    """Read-only workspace snapshot for ``install report``."""
    root = Path(root).expanduser().resolve()
    record = load_record(root)
    if not record:
        return {"ok": False, "status": "pending", "note": "工作区尚未安装"}
    repo = Path(record.get("repo") or "")
    home = Path(record.get("home") or "")
    python = Path(record.get("python") or "")
    uv = Path(record.get("uv") or "")
    venv = Path(record.get("venv") or "")
    problems = []
    if not (repo / ".git").exists():
        problems.append(f"代码目录不可用：{repo}")
    if not home.is_dir():
        problems.append(f"数据根不可用：{home}")
    if venv and not venv.is_dir():
        problems.append(f"数据根私有环境不可用：{venv}")
    if not python.is_file():
        problems.append(f"解释器不可用：{python}")
    if not uv.is_file():
        problems.append(f"uv 不可用：{uv}")
    skill = verify_skill(record)
    problems.extend(skill["problems"])
    return {
        "ok": not problems,
        "status": "ok" if not problems else "blocked",
        **record,
        "problems": problems,
    }
