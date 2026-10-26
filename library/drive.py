"""Drive abstraction: a real lark-cli drive and an in-memory fixture.

Both expose the same four operations, so quota / reconcile / evict can be
tested without a tenant:

    list(folder_token)                  -> [{name, token, type, url, size?}]
    upload(folder_token, name, path)    -> {token, url, size}
    download(token, output_path, *, kind="file") -> {path, size}
    delete(token, *, kind="file")
    ensure_folder(parent_token, name)   -> folder token
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class DriveError(RuntimeError):
    pass


class LarkDrive:
    """lark-cli wrapper. Identity defaults to the logged-in user."""

    root = ""

    def __init__(self, *, identity: str = "user"):
        self.identity = identity
        self._listing: dict[str, list[dict]] = {}

    def _folder_args(self, folder_token: str) -> list[str]:
        return ["--folder-token", folder_token] if folder_token else []

    def _run(self, *args: str, yes: bool = False, cwd: str | None = None) -> dict:
        cmd = ["lark-cli", *args, "--as", self.identity, "--format", "json"]
        if yes:
            cmd.append("--yes")
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            raise DriveError(
                f"lark-cli {' '.join(args)} returned non-JSON: {proc.stdout[:300]}"
            ) from None
        if not payload.get("ok"):
            raise DriveError(
                f"lark-cli {' '.join(args)} failed: "
                f"{payload.get('error') or proc.stderr or 'unknown error'}"
            )
        return payload.get("data") or {}

    def invalidate(self) -> None:
        self._listing.clear()

    def list(self, folder_token: str) -> list[dict]:
        data = self._run(
            "drive", "files", "list",
            *self._folder_args(folder_token), "--page-all", "--page-size", "200",
        )
        entries = []
        for row in data.get("files") or []:
            entries.append(
                {
                    "name": row.get("name") or "",
                    "token": row.get("token") or "",
                    "type": row.get("type") or "file",
                    "url": row.get("url") or "",
                    "size": int(row.get("size") or 0),
                }
            )
        self._listing[folder_token] = entries
        return entries

    def find(self, folder_token: str, name: str) -> dict | None:
        for row in self._listing.get(folder_token) or self.list(folder_token):
            if row["name"] == name:
                return row
        return None

    def ensure_folder(self, parent_token: str, name: str) -> str:
        found = self.find(parent_token, name)
        if found:
            if found["type"] != "folder":
                raise DriveError(f"{name} exists but is a {found['type']}, not a folder")
            return found["token"]
        data = self._run(
            "drive", "+create-folder", "--name", name,
            *self._folder_args(parent_token),
        )
        self.invalidate()
        token = data.get("folder_token") or data.get("token")
        if not token:
            raise DriveError(f"create-folder returned no token: {data}")
        return token

    def upload(self, folder_token: str, name: str, path: Path) -> dict:
        # lark-cli only accepts files under cwd / temp / ~/files, so upload
        # with cwd at the file's directory and pass the bare file name.
        path = Path(path).resolve()
        data = self._run(
            "drive", "+upload", "--file", path.name,
            "--folder-token", folder_token, "--name", name,
            cwd=str(path.parent),
        )
        self.invalidate()
        token = data.get("file_token") or data.get("token")
        if not token:
            raise DriveError(f"upload returned no file token: {data}")
        return {
            "token": token,
            "url": data.get("url") or f"https://feishu.cn/file/{token}",
            "size": int(data.get("size") or path.stat().st_size),
        }

    def download(self, token: str, output: Path, *, kind: str = "file") -> dict:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Same allowlist applies to --output: download into temp and move.
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            tmp = Path(fh.name)
        try:
            self._run(
                "drive", "+download", "--file-token", token,
                "--output", str(tmp), "--overwrite",
            )
            shutil.move(str(tmp), str(output))
        finally:
            tmp.unlink(missing_ok=True)
        return {"path": str(output), "size": output.stat().st_size}

    def delete(self, token: str, *, kind: str = "file") -> None:
        self._run("drive", "+delete", "--file-token", token, "--type", kind, yes=True)
        self.invalidate()


class FixtureDrive:
    """In-memory Drive used by tests and `--offline`."""

    def __init__(self, *, base_url: str = "https://example.feishu.cn"):
        self.base_url = base_url
        self.root = "root"
        self.entries: dict[str, dict] = {}
        self._counter = 0

    # ------------------------------------------------------------- helpers
    def _token(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter:06d}"

    def tree(self) -> dict:
        return {
            token: {
                "name": entry["name"],
                "type": entry["type"],
                "parent": entry["parent"],
                "size": entry["size"],
                "token": entry["token"],
            }
            for token, entry in self.entries.items()
        }

    def ensure_folder(self, parent_token: str, name: str) -> str:
        for entry in self.entries.values():
            if (
                entry["type"] == "folder"
                and entry["parent"] == parent_token
                and entry["name"] == name
            ):
                return entry["token"]
        token = self._token("fld")
        self.entries[token] = {
            "name": name, "type": "folder", "parent": parent_token,
            "size": 0, "token": token, "url": f"{self.base_url}/drive/folder/{token}",
        }
        return token

    def list(self, folder_token: str) -> list[dict]:
        return [
            {
                "name": e["name"], "token": e["token"], "type": e["type"],
                "url": e["url"], "size": e["size"],
            }
            for e in self.entries.values()
            if e["parent"] == folder_token
        ]

    def find(self, folder_token: str, name: str) -> dict | None:
        return next(
            (
                {"name": e["name"], "token": e["token"], "type": e["type"],
                 "url": e["url"], "size": e["size"]}
                for e in self.entries.values()
                if e["parent"] == folder_token and e["name"] == name
            ),
            None,
        )

    def upload(self, folder_token: str, name: str, path: Path) -> dict:
        data = Path(path).read_bytes()
        found = self.find(folder_token, name)
        token = found["token"] if found else self._token("fil")
        self.entries[token] = {
            "name": name,
            "type": "file",
            "parent": folder_token,
            "size": len(data),
            "token": token,
            "data": data,
            "url": f"{self.base_url}/file/{token}",
        }
        return {"token": token, "url": self.entries[token]["url"], "size": len(data)}

    def download(self, token: str, output: Path, *, kind: str = "file") -> dict:
        entry = self.entries.get(token)
        if not entry:
            raise DriveError(f"unknown token {token}")
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry["data"])
        return {"path": str(target), "size": entry["size"]}

    def delete(self, token: str, *, kind: str = "file") -> None:
        if token not in self.entries:
            raise DriveError(f"unknown token {token}")
        entry = self.entries[token]
        if entry["type"] == "folder":
            for child in list(self.entries):
                if self.entries[child]["parent"] == token:
                    self.delete(child, kind=self.entries[child]["type"])
        self.entries.pop(token, None)

    # ------------------------------------------------------------ test aids
    def put_bytes(self, folder_token: str, name: str, data: bytes) -> dict:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            tmp = Path(fh.name)
        try:
            return self.upload(folder_token, name, tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def corrupt(self, token: str, data: bytes = b"corrupt") -> None:
        self.entries[token]["data"] = data
        self.entries[token]["size"] = len(data)


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def token_from_url(url: str) -> str:
    """Drive file URLs end in the token; accept a bare token too."""
    value = str(url or "").strip().rstrip("/")
    return value.rsplit("/", 1)[-1] if value else ""


def copy_with_md5(source: Path, target: Path, expected: str | None = None) -> str:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    digest = md5_file(target)
    if expected and digest != expected:
        target.unlink(missing_ok=True)
        raise DriveError(f"md5 mismatch for {target.name}: {digest} != {expected}")
    return digest
