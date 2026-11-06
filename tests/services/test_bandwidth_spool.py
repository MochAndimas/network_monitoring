"""Filesystem durability boundaries and decoder stdout supervision."""

import asyncio
import hashlib
import sys
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.app.bandwidth.collector import collect_stdout
from backend.app.bandwidth.ingestion_config import load_policy, strict_json
from backend.app.bandwidth.spool import SealedSegment, SpoolError, SpoolWriter, source_manifest, spool_lock
from tests.test_utils import run


def test_rotation_recovery_and_hash_verification(tmp_path):
    source = source_manifest(tmp_path, router_id=1)
    assert source_manifest(tmp_path) == source
    with pytest.raises(SpoolError, match="router_mismatch"):
        source_manifest(tmp_path, router_id=2)
    writer = SpoolWriter(tmp_path, segment_bytes=8, max_bytes=32, max_line_bytes=8)
    writer.append(b"one\n")
    writer.append(b"two\n")
    segment = SealedSegment.from_path(next(tmp_path.glob("*.ready")))
    assert segment.read_verified(32) == b"one\ntwo\n"
    segment.path.write_bytes(b"tampered")
    with pytest.raises(SpoolError, match="checksum"):
        segment.read_verified(32)
    segment.remove()
    (tmp_path / f"{uuid4().hex}.open").write_bytes(b"crash\npartial")
    SpoolWriter(tmp_path).recover()
    recovered = SealedSegment.from_path(next(tmp_path.glob("*.ready")))
    assert recovered.read_verified(32) == b"crash\npartial"
    assert not list(tmp_path.glob("*.open"))


def test_spool_never_evicts_unread_data_at_capacity(tmp_path):
    writer = SpoolWriter(tmp_path, segment_bytes=4, max_bytes=8, max_line_bytes=4)
    writer.append(b"one\n")
    writer.append(b"two\n")
    with pytest.raises(SpoolError, match="spool_full"):
        writer.append(b"end\n")
    assert len(list(tmp_path.glob("*.ready"))) == 2


def test_capacity_wait_retries_only_unwritten_records(tmp_path):
    consumed = []

    def drain():
        for path in sorted(tmp_path.glob("*.ready")):
            consumed.append(path.read_bytes())
            path.unlink()
        return True

    writer = SpoolWriter(
        tmp_path, segment_bytes=4, max_bytes=8, max_line_bytes=4,
        max_segments=2, wait_for_capacity=drain,
    )
    writer.append_many([b"one\n", b"two\n", b"end\n"])
    writer.seal()
    consumed.extend(path.read_bytes() for path in tmp_path.glob("*.ready"))
    assert sorted(consumed) == sorted([b"one\n", b"two\n", b"end\n"])


def test_capacity_wait_publishes_open_segment_before_waiting(tmp_path):
    def drain():
        assert not list(tmp_path.glob("*.open"))
        paths = list(tmp_path.glob("*.ready"))
        assert sorted(path.read_bytes() for path in paths) == sorted([b"one\ntwo\n", b"end\n"])
        for path in paths:
            path.unlink()
        return True

    writer = SpoolWriter(
        tmp_path, segment_bytes=8, max_bytes=12, max_line_bytes=4,
        wait_for_capacity=drain,
    )
    writer.append(b"one\n")
    writer.append(b"two\n")
    writer.append(b"end\n")
    writer.append(b"new\n")
    writer.seal()


def test_capacity_wait_can_be_cancelled_without_evicting_data(tmp_path):
    writer = SpoolWriter(
        tmp_path, segment_bytes=4, max_bytes=4, max_line_bytes=4,
        wait_for_capacity=lambda: False,
    )
    writer.append(b"one\n")
    with pytest.raises(SpoolError, match="spool_full"):
        writer.append(b"two\n")
    assert next(tmp_path.glob("*.ready")).read_bytes() == b"one\n"


def test_sustained_capacity_pressure_preserves_every_record_once(tmp_path):
    consumed = []
    waits = 0

    def drain():
        nonlocal waits
        waits += 1
        paths = list(tmp_path.glob("*.ready"))
        assert len(paths) <= 2
        for path in paths:
            consumed.extend(path.read_bytes().splitlines())
            path.unlink()
        return True

    writer = SpoolWriter(
        tmp_path, segment_bytes=32, max_bytes=64, max_segments=2,
        max_line_bytes=16, wait_for_capacity=drain,
    )
    expected = [str(i).encode() for i in range(1000)]
    writer.append_many(line + b"\n" for line in expected)
    writer.seal()
    drain()
    assert waits > 10
    assert sorted(consumed) == sorted(expected)


def test_decoder_survives_slow_consumer_at_capacity(tmp_path):
    async def scenario():
        consumed = []
        waits = []

        def wait():
            waits.append(True)
            time.sleep(0.01)
            return True

        writer = SpoolWriter(
            tmp_path, segment_bytes=8, max_bytes=16, max_segments=2,
            max_line_bytes=8, wait_for_capacity=wait,
        )
        task = asyncio.create_task(collect_stdout(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'{}\\n' * 100)"],
            writer, asyncio.Event(),
        ))
        async with asyncio.timeout(10):
            while not task.done():
                await asyncio.sleep(0.03)
                for path in list(tmp_path.glob("*.ready")):
                    consumed.extend(path.read_bytes().splitlines())
                    path.unlink()
            await task
        for path in tmp_path.glob("*.ready"):
            consumed.extend(path.read_bytes().splitlines())
        assert waits
        assert consumed == [b"{}"] * 100
        assert not list(tmp_path.glob("*.open"))

    run(scenario())


def test_spool_segment_count_limit(tmp_path):
    writer = SpoolWriter(tmp_path, segment_bytes=4, max_bytes=64, max_segments=1, max_line_bytes=4)
    writer.append(b"one\n")
    with pytest.raises(SpoolError, match="spool_full"):
        writer.append(b"two\n")


def test_batch_append_rotates_only_between_records(tmp_path):
    writer = SpoolWriter(tmp_path, segment_bytes=8, max_bytes=64, max_line_bytes=8)
    writer.append_many([b"one\n", b"two\n", b"end\n"])
    writer.seal()
    assert {path.read_bytes() for path in tmp_path.glob("*.ready")} == {b"one\ntwo\n", b"end\n"}


def test_idle_rotation_and_graceful_stop_publish_before_child_exit(tmp_path):
    async def scenario():
        writer = SpoolWriter(tmp_path)
        stop = asyncio.Event()
        task = asyncio.create_task(
            collect_stdout(
                [sys.executable, "-c", "import time; print('{}',flush=True); time.sleep(10)"],
                writer,
                stop,
                rotate_seconds=0.01,
            )
        )
        try:
            for _ in range(100):
                if list(tmp_path.glob("*.ready")):
                    break
                await asyncio.sleep(0.02)
            assert list(tmp_path.glob("*.ready"))
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=6)
        assert not list(tmp_path.glob("*.open"))

    run(scenario())


def test_writer_lock_excludes_second_writer_but_allows_consumer(tmp_path):
    with (
        spool_lock(tmp_path, "writer"),
        spool_lock(tmp_path, "worker"),
        pytest.raises(SpoolError, match="writer_already_running"),
        spool_lock(tmp_path, "writer"),
    ):
        pass


def test_symlinks_and_oversized_files_are_rejected(tmp_path):
    path = tmp_path / f"{uuid4().hex}.{hashlib.sha256(b'ok').hexdigest()}.ready"
    other = tmp_path / "outside"
    other.write_bytes(b"ok")
    path.symlink_to(other)
    with pytest.raises(OSError):
        SealedSegment.from_path(path).read_verified(10)
    path.unlink()
    path.write_bytes(b"ok")
    with pytest.raises(SpoolError, match="too_large"):
        SealedSegment.from_path(path).read_verified(1)


def test_decoder_stdout_is_spooled_directly_and_final_partial_is_retained(tmp_path):
    writer = SpoolWriter(tmp_path)
    run(
        collect_stdout(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'{}\\npartial')"], writer, asyncio.Event()
        )
    )
    assert b"".join(path.read_bytes() for path in tmp_path.glob("*.ready")) == b"{}\npartial"


def test_decoder_failure_still_seals_decoded_records(tmp_path):
    writer = SpoolWriter(tmp_path)
    with pytest.raises(SpoolError, match="process_failed"):
        run(collect_stdout([sys.executable, "-c", "import sys; print('{}'); sys.exit(7)"], writer, asyncio.Event()))
    assert next(tmp_path.glob("*.ready")).read_bytes() == b"{}\n"


def test_decoder_batch_separators_are_ignored_but_malformed_records_are_retained(tmp_path):
    writer = SpoolWriter(tmp_path)
    run(
        collect_stdout(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\n{}\\n\\ninvalid\\n \\t\\n  ')"],
            writer,
            asyncio.Event(),
        )
    )
    assert b"".join(path.read_bytes() for path in tmp_path.glob("*.ready")) == b"{}\ninvalid\n"


def test_collector_default_serializes_decoder_stdout(monkeypatch):
    from backend.app.bandwidth import collector

    listeners = []

    async def capture(args):
        listeners.append(args.listen)
        assert args.rotate_seconds == 5

    monkeypatch.setattr(collector, "run", capture)
    monkeypatch.setattr(sys, "argv", ["collector", "--router-id", "2"])
    collector.main()
    assert listeners == ["netflow://:2055?count=1&workers=1"]


@pytest.mark.parametrize("payload", [b'{"bytes":1,"bytes":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_ambiguous_json_is_not_coerced(payload):
    with pytest.raises(ValueError):
        strict_json(payload)


def test_policy_is_explicit_and_digest_is_order_independent(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        '{"router_id":1,"exporter":"192.0.2.1","lan_interfaces":[13],"wan_interfaces":[10],'
        '"lan_networks":["192.168.1.0/24"],"excluded_remote_networks":[]}'
    )
    policy = load_policy(path)
    assert policy.flow.router_id == 1
    assert policy.digest == replace(policy, flow=replace(policy.flow)).digest
    path.write_text('{"router_id":1}')
    with pytest.raises(ValueError):
        load_policy(path)


def test_missing_manifest_never_reidentifies_an_existing_backlog(tmp_path):
    (tmp_path / f"{uuid4().hex}.open").write_bytes(b"existing\n")
    with pytest.raises(SpoolError, match="orphaned_spool_manifest"):
        source_manifest(tmp_path, router_id=1)
