"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiFetch, setAccessToken } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { useAuth } from "@/features/auth/auth-provider";

const NAVIGATION = [
  ["/", "Overview"], ["/daily-summary", "Daily Summary"], ["/live-monitoring", "Live Monitoring"],
  ["/devices", "Devices"], ["/alerts", "Alerts"], ["/incidents", "Incidents"],
  ["/thresholds", "Thresholds"], ["/system-health", "System Health"]
] as const;

const QUICK_NAVIGATION = NAVIGATION.filter(([href]) => ["/", "/live-monitoring", "/alerts"].includes(href));
const ACCOUNT_NAVIGATION = ["/accounts", "Kelola Akun"] as const;
const ADMIN_ONLY_PATHS = new Set(["/devices", "/thresholds", "/system-health"]);

type NavigationHref = (typeof NAVIGATION)[number][0] | typeof ACCOUNT_NAVIGATION[0];

function NavIcon({ href }: { href: NavigationHref }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<NavigationHref, React.ReactNode> = {
    "/": <><rect {...common} x="3" y="3" width="7" height="7" rx="1" /><rect {...common} x="14" y="3" width="7" height="7" rx="1" /><rect {...common} x="3" y="14" width="7" height="7" rx="1" /><rect {...common} x="14" y="14" width="7" height="7" rx="1" /></>,
    "/daily-summary": <><path {...common} d="M5 3v3m14-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z" /><path {...common} d="M8 13h3m2 0h3m-8 4h3" /></>,
    "/live-monitoring": <><path {...common} d="M3 12h4l2.1-6 4 12 2.2-6H21" /><circle {...common} cx="19" cy="5" r="2" /></>,
    "/devices": <><rect {...common} x="4" y="4" width="16" height="16" rx="2" /><path {...common} d="M8 8h8M8 12h8M8 16h3" /></>,
    "/alerts": <><path {...common} d="M18 10a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 22h4" /></>,
    "/incidents": <><path {...common} d="M12 4 3 20h18L12 4Z" /><path {...common} d="M12 9v5m0 3h.01" /></>,
    "/thresholds": <><path {...common} d="M4 7h16M4 17h16M8 4v6m8 4v6" /></>,
    "/system-health": <><path {...common} d="M4 13h4l2-5 4 10 2-5h4" /><path {...common} d="M3 4h18v16H3z" /></>,
    "/accounts": <><circle {...common} cx="12" cy="8" r="3" /><path {...common} d="M5 21c0-3.3 3.1-6 7-6s7 2.7 7 6" /></>
  };
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[href]}</svg>;
}

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isQuickMenuOpen, setIsQuickMenuOpen] = useState(false);
  const quickMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsQuickMenuOpen(false);
    }
    function closeOnOutsidePointer(event: PointerEvent) {
      if (quickMenuRef.current && !quickMenuRef.current.contains(event.target as Node)) setIsQuickMenuOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("pointerdown", closeOnOutsidePointer);
    };
  }, []);

  async function logout() {
    await apiFetch<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
    setAccessToken(undefined);
    queryClient.clear();
    router.replace("/login");
  }

  return <div className={isSidebarOpen ? "app-shell" : "app-shell app-shell-sidebar-hidden"}>
    <button className="sidebar-hover-zone" type="button" aria-label="Buka navigasi" onMouseEnter={() => setIsSidebarOpen(true)} onFocus={() => setIsSidebarOpen(true)} />
    <aside className="app-sidebar" onMouseLeave={() => setIsSidebarOpen(false)} onMouseEnter={() => setIsSidebarOpen(true)}>
      <div className="sidebar-heading">
        <Link className="app-brand" href="/"><span className="app-brand-mark" aria-hidden="true">NM</span><span><strong>Network Monitoring</strong><small>Operations workspace</small></span></Link>
      </div>
      <nav aria-label="Navigasi utama"><p className="sidebar-nav-label">Workspace</p>{NAVIGATION.filter(([href]) => user?.role === "admin" || !ADMIN_ONLY_PATHS.has(href)).map(([href, label]) =>
        <Link key={href} href={href} onClick={() => setIsSidebarOpen(false)} className={pathname === href ? "nav-link nav-link-active" : "nav-link"}><span className="nav-link-label"><NavIcon href={href} />{label}</span><span className="nav-link-arrow" aria-hidden="true">›</span></Link>
      )}</nav>
      <div className="account-panel">
        <div className="account-identity"><span className="account-avatar" aria-hidden="true">{(user?.full_name || user?.username || "U").slice(0, 1).toUpperCase()}</span><span><strong>{user?.full_name || user?.username}</strong><small>{user?.role === "admin" ? "Administrator" : "Viewer"}</small></span></div>
        <small>Sesi tersimpan hingga {formatWib(user?.session_expires_at ?? user?.expires_at)}</small>
        <button className="button-secondary" type="button" onClick={() => void logout()}>Keluar</button>
      </div>
    </aside>
    <div className="app-content">
      <div className="global-floating-menu" ref={quickMenuRef}>
          <button className="global-menu-trigger" type="button" aria-label="Buka navigasi cepat" aria-expanded={isQuickMenuOpen} aria-haspopup="menu" onClick={() => setIsQuickMenuOpen((open) => !open)}>
            <span className="global-menu-grid-icon" aria-hidden="true"><i /><i /><i /><i /></span><span className="global-menu-trigger-label">Menu</span>
          </button>
          {isQuickMenuOpen ? <div className="global-menu-popover" role="menu" aria-label="Menu cepat">
            <div className="global-menu-heading"><span>Navigasi cepat</span><small>{user?.role === "admin" ? "Admin" : "Viewer"}</small></div>
            <div className="global-menu-links">{[...QUICK_NAVIGATION, ACCOUNT_NAVIGATION].map(([href, label]) => <Link key={href} href={href} role="menuitem" onClick={() => setIsQuickMenuOpen(false)} className={pathname === href ? "global-menu-link global-menu-link-active" : "global-menu-link"}><NavIcon href={href} /><span>{label}</span></Link>)}</div>
            <div className="global-menu-footer"><button type="button" className="global-menu-logout" onClick={() => void logout()}>Keluar</button></div>
          </div> : null}
      </div>
      {children}
    </div>
  </div>;
}
