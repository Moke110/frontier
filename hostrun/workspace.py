"""Installation workspace: code, data root, private uv/Python and the run skill.

The host agent owns installation (ADR 0005).  This module makes the first
phase checkable instead of conversational:

    root/                         installation workspace (host project folder)
      .frontier/install.json      resolved code / data / interpreter / skill paths
      .frontier/bin/uv(.exe)      private uv, used when no usable uv is present
      frontier/                   code checkout (never the data root)
      frontier-archive/           data root (never inside the code checkout)
      <host skills dir>/frontier-run/SKILL.md   small launcher, not a repo copy

Rules that the functions below keep:

- an existing checkout is inspected first and never overwritten or pulled when
  it has local changes or a different origin;
- uv is reused when present, otherwise installed privately under the workspace;
- the interpreter lives in ``<repo>/.venv`` and is managed by uv only;
- no environment variable, PATH entry, registry value, service or OS task is
  written;
- a failed phase returns ``ok: false`` with an actionable reason and stays
  resumable: rerunning reuses everything already verified.
"""

from __future__ import annotations

import io
import os
import platform as platform_mod
import stat
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

from common import ensure_dir, now, read_json, write_json
from hostrun.base import HostRunError, resolve_executable

SCHEMA_VERSION = 1
RECORD_REL = Path(".frontier") / "install.json"
DEFAULT_CODE_DIRNAME = "frontier"
DEFAULT_DATA_DIRNAME = "frontier-archive"
DEFAULT_REPO_URL = "https://github.com/Moke110/frontier.git"
DEFAULT_PYTHON = "3.13"
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


def acquire(
    root: str | Path,
    *,
    repo_url: str = DEFAULT_REPO_URL,
    code_dirname: str = DEFAULT_CODE_DIRNAME,
    data_dirname: str = DEFAULT_DATA_DIRNAME,
    dry_run: bool = False,
    runner=subprocess.run,
) -> dict:
    """Acquire code safely and create the data root; never overwrite user work."""
    layout = resolve_layout(root, code_dirname=code_dirname, data_dirname=data_dirname)
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


def install_uv(
    root: str | Path,
    *,
    asset: str | None = None,
    fetch=None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> dict:
    """Install uv privately under ``<root>/.frontier/bin`` (no PATH write)."""
    asset = asset or uv_asset(platform_name, machine)
    target_dir = Path(root).expanduser().resolve() / ".frontier" / "bin"
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
    root: str | Path,
    *,
    uv_path: str | None = None,
    fetch=None,
    runner=subprocess.run,
    platform_name: str | None = None,
    machine: str | None = None,
) -> dict:
    root_path = Path(root).expanduser().resolve()
    private = root_path / ".frontier" / "bin"
    found = resolve_executable(uv_path, private_dirs=[private], names=["uv", "uv.exe"])
    installed = None
    if not found["found"]:
        installed = install_uv(
            root_path, fetch=fetch, platform_name=platform_name, machine=machine
        )
        if not installed["ok"]:
            return {
                "ok": False,
                "status": "blocked",
                "note": "未找到 uv，私有安装也失败：" + installed["error"],
                "evidence": {"source": "missing", "install": installed},
            }
        found = resolve_executable(None, private_dirs=[private], names=["uv", "uv.exe"])
    version = _run([found["path"], "--version"], runner=runner, timeout=60)
    return {
        "ok": True,
        "status": "ok",
        "path": found["path"],
        "source": found["source"],
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
    *,
    uv: str,
    python_version: str = DEFAULT_PYTHON,
    runner=subprocess.run,
    verify=None,
) -> dict:
    """Create or repair ``<repo>/.venv`` with uv, then verify imports."""
    repo = Path(repo)
    venv = repo / ".venv"
    python = _venv_python(venv)
    verify = verify or (lambda path: check_runtime(path, runner=runner))
    requirements = repo / "requirements.txt"

    existing_ok = python.exists() and verify(python).get("ok")
    if existing_ok:
        return {
            "ok": True,
            "status": "ok",
            "python": str(python),
            "uv": str(uv),
            "created": False,
            "repaired": False,
            "note": "已有私有环境通过依赖自检",
        }

    repaired = venv.exists()
    private = repo.parent / ".frontier"
    child_env = {
        **os.environ,
        "UV_PYTHON_INSTALL_DIR": str(private / "python"),
        "UV_CACHE_DIR": str(private / "uv-cache"),
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
            "uv": str(uv),
            "repaired": repaired,
        }
    if not requirements.exists():
        return {
            "ok": False,
            "status": "blocked",
            "note": f"缺少依赖声明：{requirements}",
            "python": str(python),
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
            "uv": str(uv),
            "repaired": repaired,
        }
    checked = verify(python)
    return {
        "ok": bool(checked.get("ok")),
        "status": "ok" if checked.get("ok") else "blocked",
        "python": str(python),
        "uv": str(uv),
        "created": not repaired,
        "repaired": repaired,
        "note": "" if checked.get("ok") else "依赖装好后仍无法导入 yaml/fitz：" + checked.get("error", ""),
    }


def toolchain(
    root: str | Path,
    *,
    uv_path: str | None = None,
    python_version: str = DEFAULT_PYTHON,
    fetch=None,
    runner=subprocess.run,
) -> dict:
    """Reuse or privately install uv, then create/repair the repo interpreter."""
    record = load_record(root)
    if not record.get("repo"):
        raise HostRunError("先执行 install workspace，工作区尚未记录代码与数据目录")
    uv = ensure_uv(root, uv_path=uv_path, fetch=fetch, runner=runner)
    if not uv["ok"]:
        return {"ok": False, "status": "blocked", "uv": uv, "note": uv["note"]}
    env = ensure_environment(
        record["repo"], uv=uv["path"], python_version=python_version, runner=runner
    )
    result = {"ok": env["ok"], "status": env["status"], "uv": uv, "environment": env}
    if env["ok"]:
        save_record(
            root,
            {
                **record,
                "uv": uv["path"],
                "uv_source": uv["source"],
                "uv_version": uv.get("version", ""),
                "python": env["python"],
                "python_version": python_version,
                "environment": {
                    "created": env.get("created", False),
                    "repaired": env.get("repaired", False),
                    "checked_at": now(),
                },
            },
        )
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
    problems = []
    if not (repo / ".git").exists():
        problems.append(f"代码目录不可用：{repo}")
    if not home.is_dir():
        problems.append(f"数据根不可用：{home}")
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
