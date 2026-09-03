import { expect, test } from "@playwright/test";
import { hasE2ECredentials, login } from "./auth";

const visualEnabled = process.env.E2E_VISUAL === "1";

test.describe("desktop visual regression", () => {
  test.skip(!hasE2ECredentials || !visualEnabled, "Run with dedicated credentials and E2E_VISUAL=1 to compare approved baselines.");
  test.beforeEach(async ({ page }) => login(page));

  for (const [name, path] of [["overview", "/"], ["daily-summary", "/daily-summary"], ["alerts", "/alerts"], ["incidents", "/incidents"], ["system-health", "/system-health"]]) {
    test(`${name} matches its approved desktop baseline`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(path);
      await expect(page.getByRole("main")).toHaveScreenshot(`${name}.png`, { animations: "disabled" });
    });
  }
});
