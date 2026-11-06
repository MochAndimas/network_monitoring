"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type NotificationHealth = {
  telegram_configured: boolean;
  notification_workers_alive: number;
  notification_outbox: {
    pending: number;
    dead: number;
    expired_leases: number;
    oldest_pending_age_seconds: number;
  };
};

export function notificationWarning(health: NotificationHealth): string | null {
  if (!health.telegram_configured) return "Telegram belum dikonfigurasi. Alert belum dapat dikirim.";
  const queue = health.notification_outbox;
  if (!health.notification_workers_alive) return `Worker Telegram tidak aktif. ${queue.pending} pesan menunggu pengiriman.`;
  if (queue.dead) return `${queue.dead} pesan Telegram gagal; ${queue.pending} pesan menunggu. Sistem mencoba ulang otomatis setelah 5 menit.`;
  if (queue.expired_leases || (queue.pending > 0 && queue.oldest_pending_age_seconds >= 120)) {
    return `Pengiriman Telegram tertunda: ${queue.pending} pesan menunggu, pesan tertua ${Math.floor(queue.oldest_pending_age_seconds / 60)} menit. Periksa koneksi dan log worker.`;
  }
  return null;
}

export function NotificationHealthBanner({ enabled }: { enabled: boolean }) {
  const health = useQuery({
    queryKey: ["observability", "notifications"],
    queryFn: () => apiFetch<NotificationHealth>("/observability/notifications"),
    enabled,
    refetchInterval: 15_000,
  });
  if (!enabled) return null;
  const warning = health.isError
    ? "Status pengiriman Telegram tidak dapat diperiksa."
    : health.data ? notificationWarning(health.data) : null;
  if (!warning) return null;
  return <div className="form-error" role="alert" style={{ margin: "16px 24px", padding: "12px" }}>
    {warning} <Link href="/system-health">Lihat System Health</Link>
  </div>;
}
