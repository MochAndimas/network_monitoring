import { defineConfig, devices } from "@playwright/test";

if (process.env.CI && (!process.env.E2E_USERNAME || !process.env.E2E_PASSWORD || process.env.E2E_ALLOW_MUTATIONS !== "1")) {
  throw new Error("CI E2E requires isolated fixture credentials and E2E_ALLOW_MUTATIONS=1; refusing a skipped suite.");
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure"
  },
  projects: [{ name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } }]
});
