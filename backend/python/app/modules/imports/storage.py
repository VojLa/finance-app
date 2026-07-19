from __future__ import annotations

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
    ) -> StoredImportFile:
        destination = self.path_for(batch_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256()
        size = 0

        with NamedTemporaryFile(dir=destination.parent, prefix="upload-", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
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
                temporary_path.unlink(missing_ok=True)
                raise

        checksum = digest.hexdigest()
        if destination.exists():
            existing_checksum = sha256(destination.read_bytes()).hexdigest()
            temporary_path.unlink(missing_ok=True)
            return StoredImportFile(
                size=destination.stat().st_size,
                checksum=existing_checksum,
                created=False,
            )

        os.replace(temporary_path, destination)
        return StoredImportFile(size=size, checksum=checksum, created=True)

    def remove(self, batch_id: str) -> None:
        self.path_for(batch_id).unlink(missing_ok=True)
