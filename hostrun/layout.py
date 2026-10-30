"""One resolution of the two top-level locations: code directory and archive.

ADR 0009 splits the retired single data root in two:

- the **code directory** holds the checkout, the private environment,
  configuration, run state, queue, proposals, logs, the executor lease, console
  state, installation records, initialization state and the private lark-cli;
- the **archive directory** holds only ``originals/`` (source documents) and
  ``pushes/`` (push artifacts).

To keep existing installations working, ``--home`` still names one data root.
It maps onto the new model as ``runtime = <home>`` and ``archive =
<home>/archive``; the category table below is the same relative layout in both
modes, so a legacy command reads and writes exactly the files it did before.

Nothing here starts a process or reaches a network.  ``ensure`` is the only
function that creates directories, and it never writes a file.
"""

from __future__ import annotations

from pathlib import Path

from common import now, read_json, write_json
from hostrun.base import HostRunError

RUNTIME_DIRNAME = ".frontier"
ARCHIVE_DIRNAME = "frontier-archive"
LEGACY_ARCHIVE_DIRNAME = "archive"
LAYOUT_FILENAME = "layout.json"

# One relative path per runtime-state kind.  Config, state, installation
# records and initialization state physically share ``install/``; the category
# names, not the directory count, are the contract other modules use.
CATEGORY_RELS = {
    "config": Path("install") / "config.json",
    "state": Path("install") / "state.json",
    "queue": Path("queue"),
    "proposals": Path("proposals"),
    "logs": Path("logs"),
    "lease": Path("executor"),
    "console": Path("console"),
    "install": Path("install"),
    "init": Path("install") / "initial",
    "lark_cli": Path("lark-cli"),
}

# The archive directory admits exactly these two kinds of files.
ARCHIVE_RELS = {
    "originals": Path("originals"),
    "pushes": Path("pushes"),
}

# Directories the runtime area establishes; file categories (config, state)
# live in one of these.
RUNTIME_DIRS = (
    Path("install"),
    Path("install") / "initial",
    Path("queue"),
    Path("proposals"),
    Path("logs"),
    Path("executor"),
    Path("console"),
    Path("lark-cli"),
)

AREAS = ("runtime", "archive")


def repo_root() -> Path:
    """The checkout this module lives in; the default code directory."""
    return Path(__file__).resolve().parents[1]


def default_archive(code: str | Path) -> Path:
    """``<root>/frontier-archive``, the archive sibling of a code checkout."""
    return Path(code).expanduser().resolve().parent / ARCHIVE_DIRNAME


def record_path(code: str | Path) -> Path:
    """The remembered layout of a code directory (inside its ignored runtime area)."""
    return Path(code).expanduser().resolve() / RUNTIME_DIRNAME / LAYOUT_FILENAME


def remembered_archive(code: str | Path) -> Path | None:
    """The archive a code directory was last used with, if it was recorded.

    A record written by another checkout is ignored, so moving a repository cannot
    silently point it at someone else's archive.
    """
    code_dir = Path(code).expanduser().resolve()
    record = read_json(record_path(code_dir)) or {}
    recorded_code = str(record.get("code") or "").strip()
    archive = str(record.get("archive") or "").strip()
    if not archive or not recorded_code:
        return None
    try:
        if Path(recorded_code).expanduser().resolve() != code_dir:
            return None
    except OSError:
        return None
    return Path(archive).expanduser()


def remember(resolved: dict) -> Path | None:
    """Persist the resolved layout so a custom ``--archive`` survives later runs.

    Only the new two-directory model is recorded; the legacy ``--home`` tree is
    per-invocation and deliberately leaves no marker.  A read-only checkout must
    not make a command fail, so an unwritable runtime area is ignored.
    """
    if resolved.get("mode") != "code":
        return None
    path = record_path(resolved["code"])
    try:
        write_json(
            path,
            {
                "schema_version": 1,
                "code": resolved["code"],
                "runtime": resolved["runtime"],
                "archive": resolved["archive"],
                "remembered_at": now(),
            },
        )
    except OSError:
        return None
    return path


def resolve(
    *,
    home: str | Path | None = None,
    code: str | Path | None = None,
    archive: str | Path | None = None,
) -> dict:
    """Resolve the two locations and every category path.

    ``home`` is the compatibility switch: it may not be combined with the new
    flags because the two models describe different directory trees.  A code
    directory and its archive may not contain each other, otherwise a checkout
    update or archive cleanup could delete the other side.
    """
    if home is not None and (code is not None or archive is not None):
        raise HostRunError(
            "--home 不能与 --code/--archive 同时使用；旧安装用 --home，新布局用 --code 与 --archive"
        )

    if home is not None:
        runtime = Path(home).expanduser().resolve()
        archive_root = runtime / LEGACY_ARCHIVE_DIRNAME
        code_dir = repo_root()
        mode = "home"
    else:
        code_dir = Path(code).expanduser().resolve() if code else repo_root()
        runtime = code_dir / RUNTIME_DIRNAME
        remembered = remembered_archive(code_dir) if not archive else None
        archive_root = (
            Path(archive).expanduser().resolve()
            if archive
            else (remembered.resolve() if remembered else default_archive(code_dir))
        )
        mode = "code"

    if archive_root == code_dir:
        raise HostRunError("资料目录不能就是代码目录")
    if mode == "code":
        if _is_inside(archive_root, code_dir):
            raise HostRunError("资料目录不能放在代码目录内，否则更新代码会覆盖研究资料")
        if _is_inside(code_dir, archive_root):
            raise HostRunError("代码目录不能放在资料目录内")

    return {
        "mode": mode,
        "code": str(code_dir),
        "runtime": str(runtime),
        "home": str(runtime),
        "archive": str(archive_root),
        "paths": {key: str(runtime / rel) for key, rel in CATEGORY_RELS.items()},
        "archive_paths": {
            key: str(archive_root / rel) for key, rel in ARCHIVE_RELS.items()
        },
    }


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def ensure(resolved: dict) -> dict:
    """Create the runtime categories and the two archive directories.

    A legacy ``--home`` run is left exactly as it was: the old contract created
    directories only when a command wrote something, so mapping it to the new
    model must not add empty ones.  Idempotent; never writes a file.
    """
    if resolved["mode"] != "code":
        return {**resolved, "created": False}

    created: list[str] = []
    targets = [Path(resolved["runtime"])]
    targets.extend(Path(resolved["runtime"]) / rel for rel in RUNTIME_DIRS)
    targets.extend(Path(path) for path in resolved["archive_paths"].values())
    try:
        for target in targets:
            if not target.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                created.append(str(target))
    except OSError as exc:
        raise HostRunError(
            f"无法建立运行时区或资料目录：{exc}；请检查 --code/--archive 的位置是否可写"
        ) from exc
    return {**resolved, "created": True, "created_paths": created}


def entry(resolved: dict, area: str, *parts: str) -> Path:
    """A path under one allowed area, refused if it would escape that area."""
    if area not in AREAS:
        raise HostRunError(f"未知区域 {area}；只允许 {', '.join(AREAS)}")
    root = Path(resolved[area]).resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and not _is_inside(target, root):
        raise HostRunError(f"拒绝越界写入：{target} 不在 {root} 内")
    return target
