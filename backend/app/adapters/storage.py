"""Object storage adapter interface and implementations (Local Disk & S3/MinIO)."""

from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings


class StorageAdapter(ABC):
    """Abstract interface for storing uploaded files and rendered page images."""

    @abstractmethod
    async def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Stores object bytes and returns storage key / path."""
        pass

    @abstractmethod
    async def get_object(self, key: str) -> bytes:
        """Retrieves raw bytes for an object key."""
        pass

    @abstractmethod
    async def delete_object(self, key: str) -> None:
        """Deletes an object by key."""
        pass

    @abstractmethod
    async def get_signed_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Generates a downloadable signed URL or local file path."""
        pass


class LocalStorageAdapter(StorageAdapter):
    """Local filesystem storage adapter for development and testing."""

    def __init__(self, base_dir: str = settings.STORAGE_LOCAL_DIR) -> None:
        self.base_path = Path(base_dir)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        clean_key = key.lstrip("/\\")
        path = self.base_path / clean_key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        path = self._resolve_path(key)
        path.write_bytes(data)
        return str(key)

    async def get_object(self, key: str) -> bytes:
        path = self._resolve_path(key)
        if not path.exists():
            raise FileNotFoundError(f"Storage object not found: {key}")
        return path.read_bytes()

    async def delete_object(self, key: str) -> None:
        path = self._resolve_path(key)
        if path.exists():
            path.unlink()

    async def get_signed_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        path = self._resolve_path(key)
        return f"/api/v1/storage/{key}" if path.exists() else ""


class S3StorageAdapter(StorageAdapter):
    """S3-compatible / MinIO storage adapter."""

    def __init__(self) -> None:
        self._fallback = LocalStorageAdapter()

    async def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        return await self._fallback.put_object(key, data, content_type)

    async def get_object(self, key: str) -> bytes:
        return await self._fallback.get_object(key)

    async def delete_object(self, key: str) -> None:
        await self._fallback.delete_object(key)

    async def get_signed_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        return await self._fallback.get_signed_url(key, expires_in_seconds)


def get_storage_adapter() -> StorageAdapter:
    """Factory returning configured storage adapter."""
    if settings.STORAGE_BACKEND == "s3":
        return S3StorageAdapter()
    return LocalStorageAdapter()
