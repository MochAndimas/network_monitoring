"""SNMP batches reuse expensive engines and release tasks before transport cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.monitors.device import nas_snmp, printer_snmp


async def fetch(module, oids):
    if module is printer_snmp:
        return await module._fetch_oid_values_for_version("192.0.2.1", "test", oids, mp_model=0)
    return await module._fetch_oid_values("192.0.2.1", "test", oids)


@pytest.mark.parametrize("module", [printer_snmp, nas_snmp])
def test_batch_reuses_engine_and_preserves_all_scalar_results(monkeypatch, module):
    close = Mock()
    engine = SimpleNamespace(transport_dispatcher=SimpleNamespace(close_dispatcher=close))
    factory = Mock(return_value=engine)
    monkeypatch.setattr(module, "SnmpEngine", factory)
    seen = []
    active = 0
    peak = 0
    result_type = printer_snmp.SnmpReadResult if module is printer_snmp else nas_snmp.NasSnmpReadResult

    async def read(_host, _community, oid, **kwargs):
        nonlocal active, peak
        assert kwargs["engine"] is engine
        assert close.call_count == 0
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0)
            seen.append(oid)
            return result_type("42")
        finally:
            active -= 1

    monkeypatch.setattr(module, "_snmp_get_value", read)
    oids = {"printer_uptime_ticks" if module is printer_snmp else "nas_uptime_ticks": "1.3.6.1.2.1.1.3.0"}
    oids.update({f"optional_{i}": f"1.3.6.1.4.1.{i}" for i in range(8)})
    result = asyncio.run(fetch(module, oids))
    assert result.collection_status == "ok"
    assert result.values == dict.fromkeys(oids, "42")
    assert set(seen) == set(oids.values())
    factory.assert_called_once_with()
    close.assert_called_once_with()
    if module is printer_snmp:
        assert peak == printer_snmp.SNMP_MAX_CONCURRENT_REQUESTS


@pytest.mark.parametrize("module", [printer_snmp, nas_snmp])
def test_cancelled_batch_drains_requests_before_closing_engine(monkeypatch, module):
    active = 0
    started = None

    def close():
        assert active == 0

    cleanup = Mock(side_effect=close)
    monkeypatch.setattr(
        module, "SnmpEngine", lambda: SimpleNamespace(transport_dispatcher=SimpleNamespace(close_dispatcher=cleanup))
    )

    async def read(*args, **kwargs):
        nonlocal active
        active += 1
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    monkeypatch.setattr(module, "_snmp_get_value", read)

    async def scenario():
        nonlocal started
        started = asyncio.Event()
        uptime = "printer_uptime_ticks" if module is printer_snmp else "nas_uptime_ticks"
        task = asyncio.create_task(fetch(module, {uptime: "1", "second": "2"}))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    cleanup.assert_called_once_with()


def test_printer_version_fallback_keeps_protocol_and_uptime_contract(monkeypatch):
    versions = []

    async def read(_host, _community, _oids, *, mp_model):
        versions.append(mp_model)
        return printer_snmp.SnmpFetchResult(
            values={"printer_uptime_ticks": None if mp_model == 0 else "123"},
            collection_status="timeout" if mp_model == 0 else "ok",
            protocol="snmpv1" if mp_model == 0 else "snmpv2c",
        )

    monkeypatch.setattr(printer_snmp, "_fetch_oid_values_for_version", read)
    result = asyncio.run(printer_snmp._fetch_oid_values("192.0.2.1", "test", {}))
    assert versions == [0, 1]
    assert result.protocol == "snmpv2c"
    assert result.collection_status == "ok"


def test_unreachable_printer_does_not_fan_out_optional_oids(monkeypatch):
    close = Mock()
    monkeypatch.setattr(
        printer_snmp,
        "SnmpEngine",
        lambda: SimpleNamespace(transport_dispatcher=SimpleNamespace(close_dispatcher=close)),
    )
    seen = []

    async def read(_host, _community, oid, **kwargs):
        seen.append(oid)
        return printer_snmp.SnmpReadResult(None, "timeout")

    monkeypatch.setattr(printer_snmp, "_snmp_get_value", read)
    result = asyncio.run(fetch(printer_snmp, {"printer_uptime_ticks": "uptime", "optional": "optional"}))
    assert seen == ["uptime"]
    assert result.collection_status == "timeout"
    assert result.values == {"printer_uptime_ticks": None, "optional": None}
    close.assert_called_once_with()


def test_failed_printer_base_collection_skips_toner_and_keeps_failure_status(monkeypatch):
    monkeypatch.setattr(printer_snmp, "printer_snmp_community_for_ip", lambda _ip: "test")

    async def failed(*args, **kwargs):
        return printer_snmp.SnmpFetchResult({}, "timeout", "snmpv2c")

    async def once(operation, **kwargs):
        return await operation()

    monkeypatch.setattr(printer_snmp, "_fetch_oid_values", failed)
    monkeypatch.setattr(printer_snmp, "retry_transient_collection", once)
    toner = Mock(side_effect=AssertionError("optional batch must not run"))
    monkeypatch.setattr(printer_snmp, "_fetch_oid_values_for_version", toner)
    metrics = asyncio.run(printer_snmp.collect_printer_snmp_metrics(1, "192.0.2.1"))
    status = next(m for m in metrics if m["metric_name"] == "printer_snmp_collection_status")
    assert status["metric_value"] == "timeout"
    assert status["status"] == "warning"
    toner.assert_not_called()
