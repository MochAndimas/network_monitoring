"""Authentication, validation and router scoping of bandwidth reporting."""

from .common import API_HEADERS, DeviceRepository, client_context, run


def test_bandwidth_auth_validation_and_empty_data():
    with client_context() as (client, sessions):

        async def seed():
            async with sessions() as db:
                await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Router", "ip_address": "192.0.2.1", "device_type": "mikrotik"},
                    ]
                )
                await db.commit()

        run(seed())
        url = "/bandwidth/1/usage/daily?start=2026-10-14&end=2026-10-15"
        assert client.get(url).status_code == 401
        response = client.get(url, headers=API_HEADERS)
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["completeness"] == "unverified"
        assert client.get(url.replace("/1/", "/999/"), headers=API_HEADERS).status_code == 404
        assert client.get(url + "&client_id=999", headers=API_HEADERS).status_code == 404
        assert client.get(url.replace("2026-10-15", "2026-12-15"), headers=API_HEADERS).status_code == 422
        assert client.get(url.replace("2026-10-14", "2026-10-16"), headers=API_HEADERS).status_code == 422
        assert client.get("/bandwidth/1/clients?limit=201", headers=API_HEADERS).status_code == 422
        assert client.get("/bandwidth/1/clients", headers=API_HEADERS).json() == {"items": [], "next_after_id": None}
        assert client.get(url.replace("daily", "top") + "&offset=10001", headers=API_HEADERS).status_code == 422
