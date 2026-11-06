"""Durable immutable segments. Writers never alter a published .ready file."""

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from .ingestion_config import strict_json

SEGMENT_PATTERN = re.compile(r"([0-9a-f]{32})\.([0-9a-f]{64})\.ready")


class SpoolError(RuntimeError):
    """Safe bounded failure code, without flow content or filesystem details."""


def sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def spool_lock(directory: Path, name: str) -> Iterator[None]:
    """One writer/worker per directory on the supported POSIX deployment hosts."""
    with (directory / f".{name}.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SpoolError(f"{name}_already_running") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass(frozen=True, slots=True)
class SpoolSource:
    stream_id: str
    router_id: int


def source_manifest(directory: Path, *, router_id: int | None = None) -> SpoolSource:
    path = directory / ".stream.json"
    if not path.exists():
        if type(router_id) is not int or router_id <= 0:
            raise SpoolError("source_not_initialized")
        if next(directory.glob("*.ready"), None) is not None or next(directory.glob("*.open"), None) is not None:
            raise SpoolError("orphaned_spool_manifest")
        initial = {"version": 1, "stream_id": str(uuid4()), "router_id": router_id}
        temporary = directory / ".stream.tmp"
        with temporary.open("wb") as handle:
            handle.write(json.dumps(initial).encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(directory)
    try:
        value = strict_json(path.read_bytes())
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "stream_id", "router_id"}
            or value["version"] != 1
            or not isinstance(value["stream_id"], str)
            or type(value["router_id"]) is not int
            or value["router_id"] <= 0
            or str(UUID(value["stream_id"])) != value["stream_id"]
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise SpoolError("invalid_source_manifest") from None
    if router_id is not None and value["router_id"] != router_id:
        raise SpoolError("source_router_mismatch")
    return SpoolSource(value["stream_id"], value["router_id"])


@dataclass(frozen=True, slots=True)
class SealedSegment:
    segment_id: str
    checksum: str
    path: Path

    @classmethod
    def from_path(cls, path: Path) -> "SealedSegment":
        match = SEGMENT_PATTERN.fullmatch(path.name)
        if match is None:
            raise SpoolError("invalid_segment_name")
        return cls(match[1], match[2], path)

    def read_verified(self, maximum_bytes: int) -> bytes:
        descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise SpoolError("invalid_segment_file")
            payload = handle.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise SpoolError("segment_too_large")
        if hashlib.sha256(payload).hexdigest() != self.checksum:
            raise SpoolError("segment_checksum_mismatch")
        return payload

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
        sync_directory(self.path.parent)


class SpoolWriter:
    """Single-owner writer; callers hold spool_lock for its complete lifetime.

    Capacity includes .open and .ready files. At capacity, an optional consumer
    wait callback applies backpressure; otherwise writes fail without eviction.
    Each append batch fsyncs, limiting crash exposure to
    the write in progress. Rotation publishes by rename + directory fsync.
    """

    def __init__(
        self,
        directory: Path,
        *,
        segment_bytes: int = 4 * 1024**2,
        max_bytes: int = 256 * 1024**2,
        max_segments: int = 256,
        max_line_bytes: int = 65536,
        wait_for_capacity: Callable[[], bool] | None = None,
    ) -> None:
        if not 0 < max_line_bytes <= segment_bytes <= max_bytes or max_segments <= 0:
            raise ValueError("Invalid spool limits")
        self.directory = directory
        self.segment_bytes = segment_bytes
        self.max_bytes = max_bytes
        self.max_segments = max_segments
        self.max_line_bytes = max_line_bytes
        self.wait_for_capacity = wait_for_capacity
        self.handle: BinaryIO | None = None
        self.current_path: Path | None = None
        self.size = 0

    def recover(self) -> None:
        """Publish crash remnants; a torn final record is counted as rejected by ingestion."""
        for path in sorted(self.directory.glob("*.open")):
            if not re.fullmatch(r"[0-9a-f]{32}\.open", path.name) or not path.is_file() or path.is_symlink():
                raise SpoolError("invalid_open_segment")
            if path.stat().st_size > self.segment_bytes:
                raise SpoolError("segment_too_large")
            self._publish(path)

    def _publish(self, path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        target = path.with_name(f"{path.stem}.{digest}.ready")
        if target.exists():
            raise SpoolError("segment_identity_collision")
        os.rename(path, target)
        sync_directory(self.directory)

    def append(self, line: bytes) -> None:
        self.append_many((line,))

    def append_many(self, lines: Iterable[bytes]) -> None:
        """Group available stdout records into one fsync without splitting records."""
        pending = bytearray()
        for line in lines:
            if not line or len(line) > self.max_line_bytes:
                raise SpoolError("input_line_too_large_or_empty")
            if self.size + len(pending) + len(line) > self.segment_bytes:
                if pending:
                    self._write(bytes(pending))
                    pending.clear()
                self.seal()
            pending.extend(line)
            if self.size + len(pending) >= self.segment_bytes or not line.endswith(b"\n"):
                self._write(bytes(pending))
                pending.clear()
                self.seal()
        if pending:
            self._write(bytes(pending))

    def _write(self, payload: bytes) -> None:
        while True:
            try:
                self._write_available(payload)
                return
            except SpoolError as error:
                if str(error) != "spool_full" or self.wait_for_capacity is None:
                    raise
                # Publish the current partial segment so the consumer can free
                # space. Retry only this unwritten payload, never a whole batch.
                self.seal()
                if not self.wait_for_capacity():
                    raise

    def _write_available(self, payload: bytes) -> None:
        files = []
        usage = 0
        for path in chain(self.directory.glob("*.open"), self.directory.glob("*.ready")):
            try:
                usage += path.stat().st_size
                files.append(path)
                if len(files) > self.max_segments:
                    raise SpoolError("spool_full")
            except FileNotFoundError:
                # Consumer acknowledgement can remove a ready file concurrently.
                continue
        if usage + len(payload) > self.max_bytes:
            raise SpoolError("spool_full")
        if self.handle is None:
            if len(files) >= self.max_segments:
                raise SpoolError("spool_full")
            self.current_path = self.directory / f"{uuid4().hex}.open"
            self.handle = self.current_path.open("xb")
            sync_directory(self.directory)
        self.handle.write(payload)
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.size += len(payload)

    def seal(self) -> None:
        if self.handle is None:
            return
        self.handle.close()
        self.handle = None
        assert self.current_path is not None
        self._publish(self.current_path)
        self.current_path = None
        self.size = 0
