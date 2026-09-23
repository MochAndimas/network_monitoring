"use client";

import { useTheme } from "@/lib/use-theme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  return (
    <button type="button" role="menuitemcheckbox" aria-checked={isDark}
      aria-label="Dark mode" title={isDark ? "Ganti ke light mode" : "Ganti ke dark mode"}
      className="theme-toggle" onClick={toggleTheme}>
      <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        {isDark ? <path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z" /> :
          <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>}
      </svg>
      <span>{isDark ? "Dark mode" : "Light mode"}</span>
      <span className="theme-toggle-track" aria-hidden="true"><span /></span>
    </button>
  );
}
