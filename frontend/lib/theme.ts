export type Theme = "dark" | "light";
export const THEME_STORAGE_KEY = "network-monitoring-theme";

// Apply a saved preference before paint; new visitors default to light.
export const THEME_INIT_SCRIPT = `try{document.documentElement.dataset.theme=localStorage.getItem("${THEME_STORAGE_KEY}")==="dark"?"dark":"light"}catch{document.documentElement.dataset.theme="light"}`;
