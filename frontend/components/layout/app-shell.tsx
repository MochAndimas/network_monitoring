"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { useAuth } from "@/features/auth/auth-provider";

const NAVIGATION = [
  ["/", "Overview"], ["/daily-summary", "Daily Summary"], ["/live-monitoring", "Live Monitoring"],
  ["/devices", "Devices"], ["/alerts", "Alerts"], ["/incidents", "Incidents"],
  ["/thresholds", "Thresholds"], ["/system-health", "System Health"]
] as const;

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuth();

  async function logout() {
    await apiFetch<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
    queryClient.clear();
    router.replace("/login");
  }

  return <div className="app-shell">
    <aside className="app-sidebar">
      <Link className="app-brand" href="/">Network Monitoring</Link>
      <nav aria-label="Navigasi utama">{NAVIGATION.map(([href, label]) =>
        <Link key={href} href={href} className={pathname === href ? "nav-link nav-link-active" : "nav-link"}>{label}</Link>
      )}</nav>
      <div className="account-panel">
        <strong>{user?.full_name || user?.username}</strong>
        <span>{user?.role === "admin" ? "Admin" : "Viewer"}</span>
        <small>Sesi hingga {formatWib(user?.expires_at)}</small>
        <button className="button-secondary" type="button" onClick={() => void logout()}>Keluar</button>
      </div>
    </aside>
    <div className="app-content">{children}</div>
  </div>;
}
