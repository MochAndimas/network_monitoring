"""Queue one clearly labelled production Telegram test through the real worker."""

import argparse
import asyncio
import json
from datetime import datetime
from time import monotonic
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..core.config import settings
from ..core.time import utcnow
from ..db.session import SessionLocal, engine
from ..models.notification_outbox import NotificationOutbox
from ..repositories.notification_outbox_repository import NotificationDraft, NotificationOutboxRepository


async def enqueue_test(sessions, destination: str) -> int:
    identifier = uuid4().hex
    timestamp = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S WIB")
    draft = NotificationDraft(
        idempotency_key=f"telegram-test:{identifier}",
        stream_key="telegram:operator-test",
        channel="telegram",
        destination=destination,
        message=("[TEST] Network Monitoring\n"
                 "Tes pengiriman melalui antrean dan worker Telegram.\n"
                 "Ini pesan tes, bukan insiden perangkat.\n"
                 f"Waktu: {timestamp}\nReferensi: {identifier}"),
    )
    async with sessions.begin() as db:
        return await NotificationOutboxRepository(db).enqueue(draft, now=utcnow())


async def run(timeout: int) -> int:
    try:
        if not settings.telegram_bot_token.strip() or not str(settings.telegram_chat_id).strip():
            print("GAGAL: token/chat ID belum terisi di container ini.")
            return 1
        job_id = await enqueue_test(SessionLocal, str(settings.telegram_chat_id).strip())
        print(f"Pesan tes masuk antrean. outbox_id={job_id}", flush=True)
        deadline = monotonic() + timeout
        previous = None
        while True:
            async with SessionLocal() as db:
                row = await db.get(NotificationOutbox, job_id)
                if row is None:
                    print("GAGAL: job tes tidak ditemukan.")
                    return 1
                state = (row.status, row.attempts, row.last_error)
            if state != previous:
                print(json.dumps(dict(outbox_id=job_id, status=state[0], attempts=state[1], last_error=state[2])), flush=True)
                previous = state
            if state[0] == "sent":
                print("BERHASIL: worker menandai tes sebagai sent. Cek pesan [TEST] di Telegram.")
                return 0
            if state[0] == "dead":
                print("GAGAL: job terminal; periksa kode last_error.")
                return 1
            if monotonic() >= deadline:
                print(f"Waktu tunggu habis; job {job_id} tetap di antrean dan masih bisa terkirim. Jangan ulangi tes dulu.")
                return 2
            await asyncio.sleep(2)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", required=True, help="Enqueue one real test message to configured chat")
    parser.add_argument("--timeout", type=int, choices=range(1, 121), default=60, metavar="1..120")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args.timeout))
    except Exception as error:
        # Exception text can contain connection credentials; show only its type.
        print(f"GAGAL: {type(error).__name__}. Jika job sudah tercetak, cek job itu sebelum mengulangi.")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
