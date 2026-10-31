"""Install a distribution package and keep the installation's lock and evidence.

ADR 0010 makes the distribution package the user-facing installation unit.  This
module is the runtime side of that decision:

- :func:`install_package` takes a local artifact (path or ``file://`` URL) and
  its digest, verifies the artifact *before* unpacking it, reads and validates
  ``manifest.json`` from inside the zip, extracts into
  ``<code>/.frontier/staging/<id>``, verifies every staged byte, and only then
  copies the package into the code directory and writes
  ``<code>/.frontier/dist.lock.json``.
- :func:`verify_install` checks that the lock, manifest and on-disk files still
  agree without needing the original zip.
- :func:`apply_staged` is deliberately small so ticket #96 (retention and
  rollback) can wrap it; this ticket does not delete or replace the runtime area.

No function here reaches the network: a release URL is resolved by the caller to
a local file, and a remote source is refused.  The build side lives in
:mod:`hostrun.distribution`.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from common import ensure_dir, now, read_json, write_json
from hostrun import distribution

SCHEMA_VERSION = 1
DISTRIBUTION = "package"
LOCK_REL = Path(".frontier") / "dist.lock.json"
STAGING_REL = Path(".frontier") / "staging"
RELEASES_REL = Path(".frontier") / "releases"
CURRENT_REL = Path(".frontier") / "current"
RELEASE_FILENAME = "release.json"
RELEASE_SCHEMA_VERSION = 1
MANIFEST_FILENAME = distribution.MANIFEST_FILENAME
CHANNELS = distribution.CHANNELS
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$")
_MANIFEST_LIMIT = 16 * 1024 * 1024
# Two release versions exist at any time: the active tree and one retained
# previous tree.  Installing a third version prunes the oldest retained tree.
RETAINED_LIMIT = 1


class DistError(Exception):
    """A direct API misuse (the CLI reports domain failures as blocked payloads)."""


class _InstallBlocked(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("reason", "blocked"))
        self.payload = payload


def lock_path(code: str | Path) -> Path:
    return Path(code).expanduser().resolve() / LOCK_REL


def read_lock(code: str | Path) -> dict | None:
    """Read the install lock, or ``None`` when absent/unreadable."""
    try:
        lock = read_json(lock_path(code))
    except (OSError, ValueError):
        return None
    return lock if isinstance(lock, dict) else None


def write_lock(code: str | Path, lock: dict) -> Path:
    """Write the install lock directly; never route it through ``save_config``.

    ``base.save_config`` redacts any key containing ``code``/``key``; a lock has
    no secret but must keep its literal field names and digests.
    """
    path = lock_path(code)
    write_json(path, lock)
    return path


def releases_path(code: str | Path) -> Path:
    return Path(code).expanduser().resolve() / RELEASES_REL


def current_path(code: str | Path) -> Path:
    return Path(code).expanduser().resolve() / CURRENT_REL


def read_current(code: str | Path) -> str | None:
    """Read the ``.frontier/current`` pointer, or ``None`` when absent."""
    try:
        text = current_path(code).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def _write_current(code: str | Path, version: str) -> Path:
    path = current_path(code)
    ensure_dir(path.parent)
    path.write_text(f"{version}\n", encoding="utf-8")
    return path


def _usable_version(version: object) -> bool:
    """Versions name a directory under ``.frontier/releases``; keep them inert."""
    return isinstance(version, str) and bool(_VERSION_RE.fullmatch(version))


def _manifest_at(tree: Path) -> tuple[bytes, dict] | None:
    """Read and validate ``manifest.json`` from a tree, or ``None``."""
    path = tree / MANIFEST_FILENAME
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if _validate_manifest(manifest):
        return None
    return data, manifest


def _tree_disagreements(tree: Path, manifest: dict) -> tuple[list[str], list[str]]:
    """Return ``(missing, mismatched)`` paths for a manifest against a tree."""
    missing: list[str] = []
    mismatch: list[str] = []
    for row in manifest["files"]:
        rel = row["path"]
        target = tree / Path(rel)
        if not target.is_file():
            missing.append(rel)
            continue
        try:
            data = target.read_bytes()
        except OSError:
            missing.append(rel)
            continue
        if len(data) != row["bytes"] or _sha256_bytes(data) != row["sha256"]:
            mismatch.append(rel)
    return missing, mismatch


def _release_records(code: str | Path) -> list[dict]:
    """Retained release records (``release.json``), oldest first."""
    root = releases_path(code)
    if not root.is_dir():
        return []
    records: list[dict] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            record = read_json(entry / RELEASE_FILENAME)
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        if str(record.get("version") or "") != entry.name:
            continue
        record["_path"] = str(entry)
        records.append(record)
    records.sort(
        key=lambda row: (str(row.get("installed_at") or ""), str(row.get("version") or ""))
    )
    return records


def retained_releases(code: str | Path) -> list[dict]:
    """Public summary of retained releases, newest first."""
    records = _release_records(code)
    records.reverse()
    return [
        {
            "version": str(record.get("version") or ""),
            "channel": str(record.get("channel") or ""),
            "artifact_sha256": str(record.get("artifact_sha256") or ""),
        }
        for record in records
    ]


def _retain_tree(
    code: Path,
    manifest: dict,
    manifest_bytes: bytes,
    *,
    artifact_sha256: str,
    channel: str,
    source_url: str,
    installed_at: str,
) -> Path:
    """Copy one verified tree into ``.frontier/releases/<version>``.

    The retained tree is a plain copy (no re-extraction): every manifest file
    plus the original ``manifest.json`` and a ``release.json`` metadata record.
    """
    version = manifest["version"]
    if not _usable_version(version):
        _stop(
            "invalid_version",
            f"版本号不能用作保留目录名：{version!r}",
            version=version,
        )
    target = releases_path(code) / version
    if target.exists():
        shutil.rmtree(target)
    ensure_dir(target)
    for row in manifest["files"]:
        rel = row["path"]
        source = code / Path(rel)
        if not source.is_file():
            _stop(
                "retention_failed",
                f"待保留版本缺少文件：{rel}",
                version=version,
                files=[rel],
            )
        destination = target / Path(rel)
        ensure_dir(destination.parent)
        shutil.copyfile(source, destination)
        try:
            shutil.copymode(source, destination)
        except OSError:
            pass
    (target / MANIFEST_FILENAME).write_bytes(manifest_bytes)
    record = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "version": version,
        "channel": channel,
        "artifact_sha256": artifact_sha256,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "package_file_count": len(manifest["files"]),
        "source_url": source_url,
        "installed_at": installed_at,
    }
    write_json(target / RELEASE_FILENAME, record)
    return target


def _prune_releases(code: Path, keep: str | None) -> list[str]:
    """Remove every retained release except ``keep``; return removed versions."""
    root = releases_path(code)
    if not root.is_dir():
        return []
    keep = keep or ""
    removed: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name == keep:
            continue
        shutil.rmtree(entry)
        removed.append(entry.name)
    return removed


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    stop = stop.resolve()
    while current != stop and current.is_dir():
        try:
            next(current.iterdir())
        except StopIteration:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
            continue
        except OSError:
            return
        return


def _remove_stale_files(code: Path, old_manifest: dict, new_manifest: dict) -> list[str]:
    """Delete files the previous manifest listed but the new one does not.

    Never touches the runtime area: ``.frontier`` is both rejected as a
    relative path and excluded by the resolved-path containment check.
    """
    new_paths = {row["path"] for row in new_manifest["files"]}
    code_root = code.resolve()
    removed: list[str] = []
    for row in old_manifest["files"]:
        rel = row["path"]
        if rel in new_paths or rel == MANIFEST_FILENAME:
            continue
        if not _safe_relpath(rel) or _reserved_relpath(rel):
            continue
        target = (code / Path(rel)).resolve()
        try:
            target.relative_to(code_root)
        except ValueError:
            continue
        if target.is_file():
            target.unlink()
            removed.append(rel)
            _remove_empty_parents(target.parent, code_root)
    return removed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blocked(reason: str, note: str, **extra) -> dict:
    return {
        "ok": False,
        "status": "blocked",
        "distribution": DISTRIBUTION,
        "reason": reason,
        "note": note,
        **extra,
    }


def _stop(reason: str, note: str, **extra):
    raise _InstallBlocked(_blocked(reason, note, **extra))


# ------------------------------------------------------------------- artifact
def _source_path(source: str) -> Path:
    raw = str(source or "").strip()
    if not raw:
        raise DistError("缺少发行包来源")
    if _DRIVE_RE.match(raw) or raw.startswith("\\\\"):
        return Path(raw).expanduser().resolve()
    parsed = urlparse(raw)
    if parsed.scheme == "file":
        path_text = unquote(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path_text = f"//{parsed.netloc}{path_text}"
        return Path(url2pathname(path_text)).expanduser().resolve()
    if parsed.scheme:
        raise DistError(f"不支持的发行包来源（只接受本地路径或 file:// URL）：{raw}")
    return Path(raw).expanduser().resolve()


def _digest_candidates(artifact: Path) -> list[Path]:
    if artifact.suffix.lower() == ".zip":
        return [
            artifact.with_suffix(".digest.json"),
            Path(str(artifact) + ".digest.json"),
        ]
    return [Path(str(artifact) + ".digest.json")]


def _load_digest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _stop(
            "invalid_digest",
            f"无法读取摘要文件：{path}（{exc}）",
            digest=str(path),
        )
    if not isinstance(data, dict):
        _stop("invalid_digest", f"摘要文件不是 JSON 对象：{path}", digest=str(path))
    return data


def _resolve_expected(
    artifact: Path,
    digest_path: str | Path | None,
    sha256: str | None,
) -> tuple[str, dict | None, Path | None]:
    """Resolve the expected artifact sha256 and the digest metadata.

    Explicit ``--sha256`` wins, then an explicit ``--digest``, then a sibling
    ``<artifact>.digest.json`` (for a zip also ``<stem>.digest.json``).
    """
    explicit_sha = str(sha256 or "").strip().lower()
    if explicit_sha and not _SHA256_RE.fullmatch(explicit_sha):
        _stop(
            "invalid_sha256",
            "--sha256 需要 64 位小写十六进制 SHA-256",
            sha256=explicit_sha,
        )

    digest_file: Path | None = None
    digest: dict | None = None
    if digest_path:
        digest_file = Path(digest_path).expanduser().resolve()
        if not digest_file.is_file():
            _stop(
                "digest_not_found",
                f"找不到摘要文件：{digest_file}",
                digest=str(digest_file),
            )
        digest = _load_digest(digest_file)
    elif not explicit_sha:
        for candidate in _digest_candidates(artifact):
            if candidate.is_file():
                digest_file = candidate
                break
        if digest_file is not None:
            digest = _load_digest(digest_file)

    digest_sha = ""
    if digest is not None:
        artifact_block = digest.get("artifact")
        if artifact_block is not None:
            if not isinstance(artifact_block, dict):
                _stop("invalid_digest", "摘要文件的 artifact 字段必须是对象", digest=str(digest_file))
            digest_sha = str(artifact_block.get("sha256") or "").strip().lower()
            if digest_sha and not _SHA256_RE.fullmatch(digest_sha):
                if not explicit_sha:
                    _stop(
                        "invalid_digest",
                        "摘要文件的 artifact.sha256 不是合法 SHA-256",
                        digest=str(digest_file),
                    )
                digest_sha = ""

    expected = explicit_sha or digest_sha
    if not expected:
        _stop(
            "digest_not_found",
            "未找到可用的制品摘要；请提供 --sha256 或 --digest，或把摘要文件放在制品旁边",
            artifact=str(artifact),
        )
    return expected, digest, digest_file


def _safe_relpath(name: str) -> bool:
    """Reject absolute paths, drive letters, backslashes and ``..`` components."""
    if not isinstance(name, str) or not name or "\x00" in name:
        return False
    if name.startswith(("/", "\\")) or _DRIVE_RE.match(name):
        return False
    if "\\" in name:
        return False
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    return True


def _reserved_relpath(name: str) -> bool:
    return name.split("/", 1)[0] == ".frontier"


# ------------------------------------------------------------------- manifest
def _validate_manifest(manifest: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest 必须是 JSON 对象"]
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version 必须为 1")
    for key in ("version", "channel", "built_from_commit"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            errors.append(f"缺少字符串字段 {key}")
    if manifest.get("channel") not in CHANNELS:
        errors.append(f"channel 必须是 {'/'.join(CHANNELS)}")
    compat = manifest.get("compat")
    if not isinstance(compat, dict):
        errors.append("缺少 compat 对象")
    else:
        for key in ("os", "arch", "dsh", "python"):
            if not isinstance(compat.get(key), str) or not compat[key].strip():
                errors.append(f"缺少 compat.{key}")
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("files 必须是数组")
        return errors
    seen: set[str] = set()
    for index, row in enumerate(files):
        prefix = f"files[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        path = row.get("path")
        if not isinstance(path, str) or not _safe_relpath(path):
            errors.append(f"{prefix}.path 不安全或为空：{path!r}")
        else:
            if _reserved_relpath(path):
                errors.append(f"{prefix}.path 不得写入 .frontier：{path}")
            if path == MANIFEST_FILENAME:
                errors.append(f"{prefix}.path 不得是清单自身")
            if path in seen:
                errors.append(f"{prefix}.path 重复：{path}")
            seen.add(path)
        size = row.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            errors.append(f"{prefix}.bytes 必须是非负整数")
        sha = row.get("sha256")
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            errors.append(f"{prefix}.sha256 不是合法 SHA-256")
        if not isinstance(row.get("executable"), bool):
            errors.append(f"{prefix}.executable 必须是布尔值")
    return errors


def _read_archive(
    artifact: Path,
    digest: dict | None,
    explicit_channel: str | None,
) -> tuple[zipfile.ZipFile, bytes, dict, str, str]:
    """Open the zip and validate its manifest and entry names before extraction.

    Returns ``(archive, manifest_bytes, manifest, manifest_sha, channel)``.  The
    archive is left open for the caller to extract from; every failure raises
    :class:`_InstallBlocked`.
    """
    try:
        archive = zipfile.ZipFile(artifact, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        _stop("invalid_zip", f"发行包不是可读取的 zip：{exc}", artifact=str(artifact))

    try:
        entries = archive.infolist()
        names: list[str] = []
        seen: set[str] = set()
        for info in entries:
            name = info.filename
            if name.endswith("/"):
                if not _safe_relpath(name.rstrip("/")):
                    _stop("unsafe_path", f"zip 中包含不安全路径：{name}", path=name)
                continue
            if not _safe_relpath(name):
                _stop("unsafe_path", f"zip 中包含不安全路径：{name}", path=name)
            if name in seen:
                _stop("duplicate_zip_entry", f"zip 中条目重复：{name}", path=name)
            seen.add(name)
            names.append(name)
        if MANIFEST_FILENAME not in seen:
            _stop("missing_manifest", "发行包内缺少 manifest.json", artifact=str(artifact))
        try:
            manifest_bytes = archive.read(MANIFEST_FILENAME)
        except (KeyError, OSError, RuntimeError) as exc:
            _stop("invalid_manifest", f"无法读取 manifest.json：{exc}")
        if len(manifest_bytes) > _MANIFEST_LIMIT:
            _stop("invalid_manifest", "manifest.json 过大")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            _stop("invalid_manifest", f"manifest.json 不是合法 UTF-8 JSON：{exc}")
        if isinstance(manifest, dict) and isinstance(manifest.get("files"), list):
            for row in manifest["files"]:
                if isinstance(row, dict):
                    candidate = row.get("path")
                    if not isinstance(candidate, str) or not _safe_relpath(candidate):
                        _stop(
                            "unsafe_path",
                            f"manifest.json 中包含不安全路径：{candidate!r}",
                            path=candidate,
                        )
                    if _reserved_relpath(candidate):
                        _stop(
                            "unsafe_path",
                            f"manifest.json 试图写入运行时区：{candidate}",
                            path=candidate,
                        )
        errors = _validate_manifest(manifest)
        if errors:
            _stop(
                "invalid_manifest",
                "manifest.json 校验失败：" + "；".join(errors[:5]),
                errors=errors,
            )

        file_paths = [row["path"] for row in manifest["files"]]
        expected_names = {MANIFEST_FILENAME, *file_paths}
        actual_names = set(names)
        extra = sorted(actual_names - expected_names)
        missing = sorted(expected_names - actual_names)
        if extra:
            _stop(
                "unexpected_zip_entries",
                f"zip 中有清单未列出的条目：{', '.join(extra[:5])}",
                entries=extra,
            )
        if missing:
            _stop(
                "missing_zip_entries",
                f"zip 缺少清单列出的条目：{', '.join(missing[:5])}",
                entries=missing,
            )

        manifest_sha = _sha256_bytes(manifest_bytes)
        if digest is not None:
            expected_manifest_sha = str(digest.get("manifest_sha256") or "").strip().lower()
            if expected_manifest_sha and expected_manifest_sha != manifest_sha:
                _stop(
                    "manifest_digest_mismatch",
                    "manifest.json 的 sha256 与摘要文件不一致",
                    expected=expected_manifest_sha,
                    actual=manifest_sha,
                )
            digest_version = str(digest.get("version") or "").strip()
            if digest_version and digest_version != manifest["version"]:
                _stop(
                    "version_mismatch",
                    f"摘要文件版本 {digest_version} 与清单版本 {manifest['version']} 不一致",
                    expected=digest_version,
                    actual=manifest["version"],
                )
            digest_files = digest.get("files")
            if isinstance(digest_files, int) and digest_files != len(file_paths):
                _stop(
                    "file_count_mismatch",
                    f"摘要文件记录 {digest_files} 个文件，清单列出 {len(file_paths)} 个",
                    expected=digest_files,
                    actual=len(file_paths),
                )

        digest_channel = str((digest or {}).get("channel") or "").strip()
        if digest_channel and digest_channel not in CHANNELS:
            _stop("invalid_digest", f"摘要文件的 channel 不受支持：{digest_channel}")
        channel = (explicit_channel or digest_channel or manifest["channel"]).strip()
        if channel not in CHANNELS:
            _stop("invalid_channel", f"channel 必须是 {'/'.join(CHANNELS)}：{channel}")
        if digest_channel and channel != digest_channel:
            _stop(
                "channel_conflict",
                f"显式 channel {channel} 与摘要文件 channel {digest_channel} 冲突",
                expected=digest_channel,
                actual=channel,
            )
        if channel != manifest["channel"]:
            _stop(
                "channel_mismatch",
                f"安装渠道 {channel} 与发行包清单渠道 {manifest['channel']} 不一致",
                expected=manifest["channel"],
                actual=channel,
            )
        return archive, manifest_bytes, manifest, manifest_sha, channel
    except Exception:
        archive.close()
        raise


def _compat_host(field: str) -> str:
    if field == "os":
        return distribution.normalize_os(platform.system())
    if field == "arch":
        return distribution.normalize_arch(platform.machine())
    if field == "python":
        return f"{sys.version_info.major}.{sys.version_info.minor}"
    return ""


def _compat_value_matches(value: str, host: str) -> bool:
    value = value.strip()
    if value == "*":
        return True
    if value.lower() == host.lower():
        return True
    if host == f"{sys.version_info.major}.{sys.version_info.minor}":
        match = re.match(r"^(\d+)\.(\d+)", value)
        if match and host == f"{int(match.group(1))}.{int(match.group(2))}":
            return True
        match = re.match(r"^>=\s*(\d+)\.(\d+)", value)
        if match:
            return (sys.version_info.major, sys.version_info.minor) >= (
                int(match.group(1)),
                int(match.group(2)),
            )
    return False


def _check_compat(manifest: dict) -> None:
    compat = manifest["compat"]
    for field in ("os", "arch", "python"):
        required = str(compat[field]).strip()
        host = _compat_host(field)
        canonical = required
        if field == "os":
            canonical = distribution.normalize_os(required)
        elif field == "arch":
            canonical = distribution.normalize_arch(required)
        if not _compat_value_matches(canonical, host):
            _stop(
                f"compat_{field}_mismatch",
                f"发行包要求 compat.{field}={required}，当前主机为 {host}",
                field=f"compat.{field}",
                required=required,
                host=host,
            )


# ------------------------------------------------------------------- install
def _foreign_entries(code: Path) -> list[str]:
    if not code.is_dir():
        return []
    return sorted(
        path.name
        for path in code.iterdir()
        if path.name != ".frontier"
    )


def _extract_and_verify(
    archive: zipfile.ZipFile,
    manifest: dict,
    manifest_bytes: bytes,
    stage: Path,
) -> list[str]:
    if stage.exists():
        shutil.rmtree(stage)
    ensure_dir(stage)
    bad: list[str] = []
    for row in manifest["files"]:
        target = stage / Path(row["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = archive.read(row["path"])
        except (KeyError, OSError, RuntimeError):
            bad.append(row["path"])
            continue
        target.write_bytes(data)
        try:
            target.chmod(0o755 if row["executable"] else 0o644)
        except OSError:
            pass
    (stage / MANIFEST_FILENAME).write_bytes(manifest_bytes)

    for row in manifest["files"]:
        target = stage / Path(row["path"])
        if not target.is_file():
            if row["path"] not in bad:
                bad.append(row["path"])
            continue
        data = target.read_bytes()
        if len(data) != row["bytes"] or _sha256_bytes(data) != row["sha256"]:
            if row["path"] not in bad:
                bad.append(row["path"])
    if _sha256_bytes((stage / MANIFEST_FILENAME).read_bytes()) != _sha256_bytes(manifest_bytes):
        bad.append(MANIFEST_FILENAME)
    if bad:
        shutil.rmtree(stage, ignore_errors=True)
        _stop(
            "file_verification_failed",
            "暂存文件与清单不一致：" + "，".join(bad[:5]),
            files=bad,
        )
    return [row["path"] for row in manifest["files"]]


def apply_staged(stage: str | Path, code: str | Path) -> list[str]:
    """Copy verified staged files into the code directory, manifest last.

    This function never deletes anything and refuses to write the runtime area.
    Tickets #95-#97 can wrap it; rollback/retention is intentionally *not* here.
    """
    stage_path = Path(stage).expanduser().resolve()
    code_path = Path(code).expanduser().resolve()
    if not stage_path.is_dir():
        raise DistError(f"暂存目录不存在：{stage_path}")
    if code_path == stage_path:
        raise DistError("暂存目录不能是代码目录")
    files = sorted(
        (path for path in stage_path.rglob("*") if path.is_file()),
        key=lambda path: (
            path.relative_to(stage_path).as_posix() == MANIFEST_FILENAME,
            path.relative_to(stage_path).as_posix(),
        ),
    )
    if not files:
        raise DistError(f"暂存目录为空：{stage_path}")
    code_path.mkdir(parents=True, exist_ok=True)
    applied: list[str] = []
    for source in files:
        rel = source.relative_to(stage_path)
        rel_posix = rel.as_posix()
        if _reserved_relpath(rel_posix):
            raise DistError(f"拒绝把暂存文件写入运行时区：{rel_posix}")
        target = code_path / rel
        ensure_dir(target.parent)
        shutil.copyfile(source, target)
        try:
            shutil.copymode(source, target)
        except OSError:
            pass
        applied.append(rel_posix)
    return applied


def _success(
    code: Path,
    manifest: dict,
    artifact_sha: str,
    artifact: Path,
    source_url: str,
    channel: str,
    extracted: bool,
    installed_at: str,
    previous_version: str = "",
) -> dict:
    manifest_files = manifest["files"]
    total_bytes = sum(row["bytes"] for row in manifest_files)
    if extracted:
        note = (
            f"已从 {artifact.name} 安装 frontier {manifest['version']}"
            f"（{channel}），安装锁已写入；可用 install verify 复核磁盘内容"
        )
    else:
        note = "同一版本且校验通过，本次未重复解压，安装锁与磁盘均未改动"
    return {
        "ok": True,
        "status": "ok",
        "distribution": DISTRIBUTION,
        "version": manifest["version"],
        "channel": channel,
        "artifact": artifact.name,
        "artifact_sha256": artifact_sha,
        "source_url": source_url,
        "code": str(code),
        "lock": str(lock_path(code)),
        "manifest": str(code / MANIFEST_FILENAME),
        "current": str(current_path(code)),
        "previous_version": previous_version,
        "retained": retained_releases(code),
        "files": len(manifest_files),
        "file_count": len(manifest_files),
        "package_file_count": len(manifest_files),
        "bytes": total_bytes,
        "extracted": extracted,
        "installed_at": installed_at,
        "note": note,
    }


def install_package(
    code: str | Path,
    *,
    from_source: str,
    digest_path: str | Path | None = None,
    sha256: str | None = None,
    channel: str | None = None,
) -> dict:
    """Install a distribution package and write its install lock.

    Failure is a structured ``status=blocked`` payload; the code directory and
    the lock are not modified before the artifact, manifest and compatibility
    checks all pass.
    """
    code_path = Path(code).expanduser().resolve()
    try:
        try:
            artifact = _source_path(from_source)
        except DistError as exc:
            _stop("unsupported_source", str(exc), source=str(from_source))
        if not artifact.is_file():
            _stop(
                "source_not_found",
                f"发行包不存在或不是文件：{artifact}",
                source=str(from_source),
            )
        source_url = artifact.as_uri()
        expected_sha, digest, _digest_file = _resolve_expected(artifact, digest_path, sha256)

        actual_sha = _sha256(artifact)
        if actual_sha != expected_sha:
            _stop(
                "digest_mismatch",
                "制品摘要不符，未解压、未写安装锁；请重新下载发行包",
                expected=expected_sha,
                actual=actual_sha,
                artifact=str(artifact),
            )
        if digest is not None:
            digest_bytes = (digest.get("artifact") or {}).get("bytes")
            if isinstance(digest_bytes, int) and digest_bytes != artifact.stat().st_size:
                _stop(
                    "artifact_size_mismatch",
                    "制品字节数与摘要文件不一致",
                    expected=digest_bytes,
                    actual=artifact.stat().st_size,
                )
        explicit_channel = str(channel or "").strip() or None
        if explicit_channel and explicit_channel not in CHANNELS:
            _stop("invalid_channel", f"channel 必须是 {'/'.join(CHANNELS)}：{explicit_channel}")
        if digest is not None:
            digest_channel = str(digest.get("channel") or "").strip()
            if explicit_channel and digest_channel and explicit_channel != digest_channel:
                _stop(
                    "channel_conflict",
                    f"显式 channel {explicit_channel} 与摘要文件 channel {digest_channel} 冲突",
                    expected=digest_channel,
                    actual=explicit_channel,
                )

        archive, manifest_bytes, manifest, manifest_sha, effective_channel = _read_archive(
            artifact, digest, explicit_channel
        )
        try:
            _check_compat(manifest)

            lock = read_lock(code_path)
            if (
                lock
                and lock.get("version") == manifest["version"]
                and lock.get("artifact_sha256") == actual_sha
            ):
                verification = verify_install(code_path)
                if verification.get("status") == "verified":
                    return _success(
                        code_path,
                        manifest,
                        actual_sha,
                        artifact,
                        source_url,
                        effective_channel,
                        False,
                        str(lock.get("installed_at") or ""),
                    )

            conflicts = _foreign_entries(code_path)
            if lock is None and conflicts:
                _stop(
                    "foreign_code_dir",
                    "代码目录非空且没有安装锁，拒绝覆盖：" + "，".join(conflicts[:5]),
                    conflicts=conflicts[:20],
                )

            stage = code_path / STAGING_REL / actual_sha[:16]
            _extract_and_verify(archive, manifest, manifest_bytes, stage)
        finally:
            archive.close()

        previous_manifest: dict | None = None
        previous_version = ""
        try:
            if lock is not None:
                lock_version = str(lock.get("version") or "")
                if manifest["version"] != lock_version:
                    if lock.get("distribution") != DISTRIBUTION:
                        _stop(
                            "unsupported_distribution",
                            "当前安装不是发行包安装，拒绝按发行包升级",
                            distribution=lock.get("distribution"),
                        )
                    previous = _manifest_at(code_path)
                    if previous is None:
                        _stop(
                            "previous_manifest_unreadable",
                            "代码目录现有 manifest.json 缺失或无效；无法保留可回滚的旧版本",
                            version=lock_version,
                        )
                    previous_bytes, previous_manifest = previous
                    if previous_manifest["version"] != lock_version:
                        _stop(
                            "previous_manifest_unreadable",
                            "代码目录的 manifest.json 版本与安装锁不一致，无法保留旧版本",
                            expected=lock_version,
                            actual=previous_manifest["version"],
                        )
                    if _sha256_bytes(previous_bytes) != str(
                        lock.get("manifest_sha256") or ""
                    ):
                        _stop(
                            "previous_install_unverified",
                            "现有安装的 manifest.json 摘要与安装锁不一致；拒绝在没有可回滚副本时升级",
                            version=lock_version,
                        )
                    missing, mismatch = _tree_disagreements(code_path, previous_manifest)
                    if missing or mismatch:
                        _stop(
                            "previous_install_unverified",
                            "现有安装的文件与清单不一致；请先重新安装当前版本修复，再升级",
                            version=lock_version,
                            missing=missing[:20],
                            mismatch=mismatch[:20],
                        )
                    _retain_tree(
                        code_path,
                        previous_manifest,
                        previous_bytes,
                        artifact_sha256=str(lock.get("artifact_sha256") or ""),
                        channel=str(lock.get("channel") or ""),
                        source_url=str(lock.get("source_url") or ""),
                        installed_at=str(lock.get("installed_at") or ""),
                    )
                    previous_version = lock_version
                    _prune_releases(code_path, keep=previous_version)

            apply_staged(stage, code_path)
            if previous_manifest is not None:
                _remove_stale_files(code_path, previous_manifest, manifest)
        except _InstallBlocked:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        except (OSError, DistError) as exc:
            shutil.rmtree(stage, ignore_errors=True)
            _stop("apply_failed", f"写入代码目录失败：{exc}")
        shutil.rmtree(stage, ignore_errors=True)
        try:
            stage.parent.rmdir()
        except OSError:
            pass

        installed_at = now()
        lock = {
            "schema_version": SCHEMA_VERSION,
            "distribution": DISTRIBUTION,
            "version": manifest["version"],
            "channel": effective_channel,
            "artifact_sha256": actual_sha,
            "source_url": source_url,
            "installed_at": installed_at,
            "requires": dict(manifest["compat"]),
            "skill_digest": "",
            "package_file_count": len(manifest["files"]),
            "manifest_sha256": manifest_sha,
        }
        if previous_version:
            lock["previous_version"] = previous_version
        write_lock(code_path, lock)
        _write_current(code_path, manifest["version"])
        return _success(
            code_path,
            manifest,
            actual_sha,
            artifact,
            source_url,
            effective_channel,
            True,
            installed_at,
            previous_version,
        )
    except _InstallBlocked as exc:
        return exc.payload
    except OSError as exc:
        return _blocked(
            "install_failed",
            f"安装过程遇到文件系统错误：{exc}",
            code=str(code_path),
        )


# -------------------------------------------------------------------- verify
def _mismatch_payload(
    code: Path,
    manifest: dict | None,
    *,
    manifest_path: Path,
    lock: dict,
    missing: list[str] | None = None,
    mismatch: list[dict] | None = None,
    extra: list[str] | None = None,
    lock_mismatch: list[dict] | None = None,
    reason: str = "install_mismatch",
    note: str = "安装锁与磁盘内容不一致；请按 missing/mismatch 明细修复或重新安装",
) -> dict:
    return {
        "ok": False,
        "status": "mismatch",
        "distribution": DISTRIBUTION,
        "reason": reason,
        "version": (manifest or {}).get("version") or lock.get("version"),
        "channel": (manifest or {}).get("channel") or lock.get("channel"),
        "artifact_sha256": lock.get("artifact_sha256"),
        "code": str(code),
        "lock": str(lock_path(code)),
        "manifest": str(manifest_path),
        "missing": sorted(missing or []),
        "mismatch": mismatch or [],
        "extra_manifest_files": sorted(extra or []),
        "lock_mismatch": lock_mismatch or [],
        "note": note,
    }


def _lock_comparisons(manifest: dict, manifest_sha: str, lock: dict) -> list[dict]:
    comparisons = [
        ("distribution", DISTRIBUTION, lock.get("distribution")),
        ("version", manifest["version"], lock.get("version")),
        ("channel", manifest["channel"], lock.get("channel")),
        ("manifest_sha256", manifest_sha, lock.get("manifest_sha256")),
        (
            "package_file_count",
            len(manifest["files"]),
            lock.get("package_file_count"),
        ),
        ("requires", manifest["compat"], lock.get("requires")),
    ]
    out: list[dict] = []
    for field, expected, actual in comparisons:
        if actual != expected:
            out.append({"field": field, "expected": expected, "actual": actual})
    artifact_sha = str(lock.get("artifact_sha256") or "")
    if not _SHA256_RE.fullmatch(artifact_sha):
        out.append(
            {
                "field": "artifact_sha256",
                "expected": "64 lowercase hex characters",
                "actual": artifact_sha,
            }
        )
    return out


def verify_install(code: str | Path) -> dict:
    """Check the lock, manifest and every file under the code directory."""
    code_path = Path(code).expanduser().resolve()
    lock = read_lock(code_path)
    if lock is None:
        return _blocked(
            "no_install_lock",
            "代码目录中没有 .frontier/dist.lock.json，无法按发行包安装校验",
            code=str(code_path),
            lock=str(lock_path(code_path)),
        )
    manifest_path = code_path / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return _mismatch_payload(
            code_path,
            None,
            manifest_path=manifest_path,
            lock=lock,
            missing=[MANIFEST_FILENAME],
            reason="manifest_missing",
            note="安装锁存在，但代码目录缺少 manifest.json；无法证明安装内容",
        )
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _mismatch_payload(
            code_path,
            None,
            manifest_path=manifest_path,
            lock=lock,
            mismatch=[{"path": MANIFEST_FILENAME, "field": "json", "error": str(exc)}],
            reason="invalid_manifest",
            note="manifest.json 无法解析，无法校验安装",
        )
    errors = _validate_manifest(manifest)
    if errors:
        return _mismatch_payload(
            code_path,
            manifest if isinstance(manifest, dict) else None,
            manifest_path=manifest_path,
            lock=lock,
            mismatch=[{"path": MANIFEST_FILENAME, "field": "schema", "errors": errors}],
            reason="invalid_manifest",
        )

    missing: list[str] = []
    mismatch: list[dict] = []
    listed: set[str] = set()
    for row in manifest["files"]:
        rel = row["path"]
        listed.add(rel)
        if _reserved_relpath(rel):
            mismatch.append(
                {
                    "path": rel,
                    "field": "path",
                    "expected": "outside .frontier",
                    "actual": rel,
                }
            )
            continue
        target = code_path / Path(rel)
        if not target.is_file():
            missing.append(rel)
            continue
        try:
            data = target.read_bytes()
        except OSError as exc:
            mismatch.append(
                {
                    "path": rel,
                    "field": "read",
                    "expected": "readable file",
                    "actual": str(exc),
                }
            )
            continue
        actual_sha = _sha256_bytes(data)
        if len(data) != row["bytes"] or actual_sha != row["sha256"]:
            fields = []
            if len(data) != row["bytes"]:
                fields.append("bytes")
            if actual_sha != row["sha256"]:
                fields.append("sha256")
            mismatch.append(
                {
                    "path": rel,
                    "field": ",".join(fields),
                    "expected": {"bytes": row["bytes"], "sha256": row["sha256"]},
                    "actual": {"bytes": len(data), "sha256": actual_sha},
                }
            )

    extra: list[str] = []
    for dirpath, dirnames, filenames in os.walk(code_path):
        # The runtime area contains the lock, staging and the private/bundled
        # environment; it is never package content and may be very large.
        dirnames[:] = sorted(name for name in dirnames if name != ".frontier")
        current = Path(dirpath)
        for name in sorted(filenames):
            path = current / name
            rel = path.relative_to(code_path).as_posix()
            if rel == MANIFEST_FILENAME or _reserved_relpath(rel):
                continue
            if rel not in listed:
                extra.append(rel)

    lock_mismatch = _lock_comparisons(manifest, _sha256_bytes(manifest_bytes), lock)
    if missing or mismatch or extra or lock_mismatch:
        return _mismatch_payload(
            code_path,
            manifest,
            manifest_path=manifest_path,
            lock=lock,
            missing=missing,
            mismatch=mismatch,
            extra=extra,
            lock_mismatch=lock_mismatch,
        )
    return {
        "ok": True,
        "status": "verified",
        "distribution": DISTRIBUTION,
        "version": manifest["version"],
        "channel": manifest["channel"],
        "artifact_sha256": lock.get("artifact_sha256"),
        "code": str(code_path),
        "lock": str(lock_path(code_path)),
        "manifest": str(manifest_path),
        "files": len(manifest["files"]),
        "bytes": sum(row["bytes"] for row in manifest["files"]),
        "missing": [],
        "mismatch": [],
        "extra_manifest_files": [],
        "lock_mismatch": [],
        "note": f"安装锁与磁盘内容一致：frontier {manifest['version']}（{manifest['channel']}）",
    }
