"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const nav = [["Overview", "/"], ["Daily Summary", "/daily-summary"], ["Live Monitoring", "/live-monitoring"], ["Devices", "/devices"], ["Alerts", "/alerts"], ["Incidents", "/incidents"], ["Thresholds", "/thresholds"], ["System Health", "/system-health"]] as const;
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth(); const pathname = usePathname(); const router = useRouter();
  const accountNav = [["Profil & Session", "/profile"], ...(user?.role === "admin" ? [["Administration", "/admin"] as const] : [])];
  return <div className="app-shell"><aside className="sidebar"><Link className="brand" href="/">Network Monitoring</Link><nav className="nav">{nav.map(([label, href]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}>{label}</Link>)}<div className="nav-divider" />{accountNav.map(([label, href]) => <Link key={href} href={href} className={pathname === href || pathname.startsWith(`${href}/`) ? "active" : ""}>{label}</Link>)}</nav><div className="user-card"><div>{user?.full_name || user?.username}</div><div>{user?.role}</div><button className="button" style={{ marginTop: 12 }} onClick={() => logout().finally(() => router.replace("/login"))}>Keluar</button></div></aside><main className="main">{children}</main></div>;
}
