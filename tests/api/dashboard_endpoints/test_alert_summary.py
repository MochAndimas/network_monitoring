"""Alert summaries count the complete filtered set, independently of table pages."""

from .common import Alert, API_HEADERS, DeviceRepository, client_context, run, utcnow


def test_alert_summary_matches_filtered_pages_and_counts_alerts_not_devices():
    with client_context() as (client, session_factory):
        assert client.get("/alerts/active/summary", headers=API_HEADERS).json() == {}

        async def seed():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Ruijie 1", "ip_address": "192.0.2.1", "device_type": "access_point", "site": "HO"},
                        {"name": "Ruijie 2", "ip_address": "192.0.2.2", "device_type": "access_point", "site": "HO"},
                        {"name": "Canon", "ip_address": "192.0.2.3", "device_type": "printer", "site": "RO"},
                    ]
                )
                for device, kind, severity, status in [
                    (devices[0], "ping_latency_anomaly", "warning", "active"),
                    (devices[1], "ping_latency_anomaly", "warning", "active"),
                    (devices[2], "printer_ink_low", "warning", "active"),
                    (devices[2], "printer_error_state", "critical", "active"),
                    (devices[2], "printer_error_state", "high", "resolved"),
                ]:
                    db.add(
                        Alert(
                            device_id=device.id,
                            alert_type=kind,
                            severity=severity,
                            status=status,
                            message=f"{device.name} toner sample",
                            created_at=utcnow(),
                        )
                    )
                await db.commit()
                return devices[2].id

        printer_id = run(seed())
        summary = client.get("/alerts/active/summary", headers=API_HEADERS)
        assert summary.status_code == 200
        assert summary.json() == {"warning": 3, "critical": 1}
        for offset in (0, 3, 4):
            response = client.get("/alerts/active/paged", params={"limit": 1, "offset": offset}, headers=API_HEADERS)
            assert response.status_code == 200
            payload = response.json()
            assert payload["severity_counts"] == summary.json()
            assert payload["meta"]["total"] == 4
            assert len(payload["items"]) == (1 if offset < 4 else 0)

        for filters, expected in [
            ({"site": " ho "}, {"warning": 2}),
            ({"search": "Ruijie"}, {"warning": 2}),
            ({"device_id": printer_id}, {"warning": 1, "critical": 1}),
            (
                {
                    "device_id": printer_id,
                    "site": "ro",
                    "severity": " WARNING ",
                    "alert_type": "printer_ink_low",
                    "search": "toner",
                },
                {"warning": 1},
            ),
            ({"severity": "high"}, {}),
        ]:
            response = client.get("/alerts/active/paged", params={**filters, "limit": 1}, headers=API_HEADERS)
            assert response.status_code == 200
            payload = response.json()
            assert payload["severity_counts"] == expected
            assert payload["meta"]["total"] == sum(expected.values())
            assert len(payload["items"]) == min(1, sum(expected.values()))
