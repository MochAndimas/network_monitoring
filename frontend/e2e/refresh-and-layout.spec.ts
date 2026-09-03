import { expect, test } from "@playwright/test";
import { hasE2ECredentials, login } from "./auth";

test.describe("monitoring resilience", () => {
  test.skip(!hasE2ECredentials, "Set dedicated E2E credentials before running browser tests.");
  test.beforeEach(async ({ page }) => login(page));

  test("alerts refetches automatically", async ({ page }) => {
    let requests = 0;
    page.on("request", (request) => {
      if (request.url().includes("/alerts/active/paged")) requests += 1;
    });
    await page.goto("/alerts");
    await expect(page.getByRole("heading", { name: "Alerts" })).toBeVisible();
    await expect.poll(() => requests, { timeout: 20_000 }).toBeGreaterThan(1);
  });

  test("core pages remain usable on a narrow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const path of ["/", "/daily-summary", "/alerts", "/incidents", "/system-health"]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.locator("body").evaluate((body) => body.clientWidth));
    }
  });
});
