from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import UploadFile


class UploadTooLargeError(ValueError):
    pass


class UploadStore:
    """Bounded disk spool shared by the API and ingestion worker."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, upload: UploadFile, max_bytes: int) -> Path:
        path = self.root / f"{uuid.uuid4().hex}.upload"
        total = 0
        try:
            with path.open("xb") as target:
                path.chmod(0o600)
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise UploadTooLargeError("Uploaded file exceeds size limit")
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if total == 0:
                raise ValueError("Uploaded file is empty")
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def delete(self, path: str | Path) -> None:
        candidate = Path(path).resolve()
        if candidate.parent != self.root or candidate.suffix != ".upload":
            raise ValueError("Refusing to delete a path outside the upload spool")
        candidate.unlink(missing_ok=True)

    def promote(self, path: str | Path, job_id: str) -> Path:
        candidate = Path(path).resolve()
        if candidate.parent != self.root or candidate.suffix != ".upload":
            raise ValueError("Upload path is outside the spool")
        normalized_job_id = str(uuid.UUID(job_id))
        target = self.root / f"{normalized_job_id}.upload"
        candidate.replace(target)
        return target

    def path_for_job(self, job_id: str) -> Path:
        return self.root / f"{uuid.UUID(job_id)}.upload"

    def validate_job_path(self, job_id: str, path: str | Path) -> Path:
        expected = self.path_for_job(job_id).resolve()
        if Path(path).resolve() != expected:
            raise ValueError("Ingestion path does not match its job ID")
        return expected
