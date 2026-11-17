"""Isolated working copies for Linux decks."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path


_GENERATED = {".manimble", "__pycache__", "media", "slides"}


def _base_dir(kind: str) -> Path:
    variable = "XDG_DATA_HOME" if kind == "data" else "XDG_CACHE_HOME"
    fallback = Path.home() / (".local/share" if kind == "data" else ".cache")
    return Path(os.environ.get(variable, fallback)) / "manimble"


def _files(root: Path):
    for path in root.rglob("*"):
        if any(part in _GENERATED for part in path.relative_to(root).parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


class Workspace:
    """Keep edits in a private deck copy until the user saves them to the original."""

    def __init__(self, deck: str | Path):
        self.original = Path(deck).expanduser().resolve(strict=True)
        if not self.original.is_dir():
            raise ValueError(f"Deck is not a folder: {self.original}")

        self.root = _base_dir("data") / "work" / f"{self.original.name}-{uuid.uuid4().hex}"
        self.project_root = self.root / self.original.parent.name
        self.work = self.project_root / self.original.name
        self.project_root.mkdir(parents=True, exist_ok=True)
        try:
            for sibling in self.original.parent.iterdir():
                if sibling != self.original:
                    (self.project_root / sibling.name).symlink_to(sibling, target_is_directory=sibling.is_dir())
            shutil.copytree(self.original, self.work, ignore=shutil.ignore_patterns("__pycache__", ".manimble"))
        except Exception:
            self.discard()
            raise

        self.cache = _base_dir("cache") / "render" / hashlib.sha256(
            os.fsencode(str(self.original))
        ).hexdigest()[:16]
        self.cache.mkdir(parents=True, exist_ok=True)
        self._baseline = {
            path.relative_to(self.work): _digest(path)
            for path in _files(self.work)
        }

    @property
    def changed_files(self) -> list[Path]:
        current = {path.relative_to(self.work): path for path in _files(self.work)}
        changed = [
            rel for rel, path in current.items()
            if rel not in self._baseline or _digest(path) != self._baseline[rel]
        ]
        deleted = self._baseline.keys() - current.keys()
        return sorted(set(changed) | deleted)

    def save(self) -> list[Path]:
        if not self.original.is_dir():
            raise FileNotFoundError(f"The original deck folder no longer exists: {self.original}")

        changed = self.changed_files
        conflicts = []
        for rel in changed:
            source = self.original / rel
            expected = self._baseline.get(rel)
            actual = _digest(source) if source.is_file() else None
            if expected != actual:
                conflicts.append(str(rel))
        if conflicts:
            raise RuntimeError("Deck changed outside Manimble; save refused for: " + ", ".join(conflicts))

        for rel in changed:
            source, destination = self.work / rel, self.original / rel
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=".manimble-save-", dir=destination.parent)
                os.close(fd)
                try:
                    shutil.copyfile(source, temporary)
                    shutil.copystat(source, temporary)
                    os.replace(temporary, destination)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                self._baseline[rel] = _digest(source)
            else:
                if destination.is_file():
                    destination.unlink()
                self._baseline.pop(rel, None)
        return changed

    def discard(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
