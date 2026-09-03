import { expect, test } from "@playwright/test";
import { hasE2ECredentials, login } from "./auth";

test.describe("dashboard critical path", () => {
  test.skip(!hasE2ECredentials, "Set E2E_USERNAME and E2E_PASSWORD to run against a dedicated test environment.");

  test.beforeEach(async ({ page }) => login(page));

  test("navigates every protected route", async ({ page }) => {
    const routes = [
      ["Overview", "/"], ["Daily Summary", "/daily-summary"], ["Live Monitoring", "/live-monitoring"],
      ["Devices", "/devices"], ["Alerts", "/alerts"], ["Incidents", "/incidents"],
      ["Thresholds", "/thresholds"], ["System Health", "/system-health"]
    ] as const;
    for (const [label, path] of routes) {
      await page.getByRole("link", { name: label }).click();
      await expect(page).toHaveURL(new RegExp(`${path === "/" ? "\\/$" : path}$`));
      await expect(page.getByRole("main")).toBeVisible();
    }
  });

  test("exports active alerts as CSV", async ({ page }) => {
    await page.goto("/alerts");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download CSV" }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  });

  test("redirects an expired session to login", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/alerts");
    await expect(page).toHaveURL(/\/login\?reason=session-expired/);
  });
});
