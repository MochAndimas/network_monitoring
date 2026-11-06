import { describe, expect, it } from "vitest";
import { notificationWarning, type NotificationHealth } from "./notification-health-banner";

const healthy: NotificationHealth = {
  telegram_configured: true,
  notification_workers_alive: 1,
  notification_outbox: { pending: 0, dead: 0, expired_leases: 0, oldest_pending_age_seconds: 0 },
};

describe("Telegram health warning", () => {
  it("shows failed deliveries even with a healthy worker", () => {
    expect(notificationWarning({ ...healthy, notification_outbox: { ...healthy.notification_outbox, dead: 1, pending: 14 } })).toContain("1 pesan Telegram gagal; 14 pesan menunggu");
  });
  it("shows delayed deliveries and offline workers", () => {
    expect(notificationWarning({ ...healthy, notification_outbox: { ...healthy.notification_outbox, pending: 2, oldest_pending_age_seconds: 180 } })).toContain("tertua 3 menit");
    expect(notificationWarning({ ...healthy, notification_workers_alive: 0 })).toContain("tidak aktif");
  });
  it("does not warn for a healthy queue", () => {
    expect(notificationWarning(healthy)).toBeNull();
  });
});
