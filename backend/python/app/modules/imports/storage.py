from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class StoredImportFile:
    size: int
    checksum: str
    created: bool


class ImportFileTooLargeError(Exception):
    pass


class ImportFileMismatchError(Exception):
    pass


class LocalImportStorage:
    def __init__(self, root: Path | None = None) -> None:
        configured = os.getenv("IMPORT_STORAGE_ROOT", ".data/imports")
        self.root = root or Path(configured)

    def path_for(self, batch_id: str) -> Path:
        safe_id = sha256(batch_id.encode("utf-8")).hexdigest()
        return self.root / safe_id / "raw"

    async def store(
        self,
        *,
        batch_id: str,
        chunks: AsyncIterator[bytes],
        max_bytes: int,
        expected_size: int | None,
        expected_checksum: str,
    ) -> StoredImportFile:
        destination = self.path_for(batch_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256()
        size = 0

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=destination.parent,
                prefix="upload-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise ImportFileTooLargeError()
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

        checksum = digest.hexdigest()
        if (expected_size is not None and size != expected_size) or checksum != expected_checksum:
            temporary_path.unlink(missing_ok=True)
            raise ImportFileMismatchError()

        lock_path = destination.parent / "publish.lock"
        lock_descriptor: int | None = None
        try:
            while lock_descriptor is None:
                try:
                    lock_descriptor = os.open(
                        lock_path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                except FileExistsError:
                    await asyncio.sleep(0.01)

            if destination.exists():
                existing = self._metadata(destination)
                temporary_path.unlink(missing_ok=True)
                return StoredImportFile(
                    size=existing.size,
                    checksum=existing.checksum,
                    created=False,
                )

            os.replace(temporary_path, destination)
            return StoredImportFile(size=size, checksum=checksum, created=True)
        finally:
            temporary_path.unlink(missing_ok=True)
            if lock_descriptor is not None:
                os.close(lock_descriptor)
                lock_path.unlink(missing_ok=True)

    def remove(self, batch_id: str) -> None:
        self.path_for(batch_id).unlink(missing_ok=True)

    @staticmethod
    def _metadata(path: Path) -> StoredImportFile:
        digest = sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        return StoredImportFile(size=size, checksum=digest.hexdigest(), created=False)
