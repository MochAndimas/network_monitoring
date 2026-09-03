import { expect, test } from "@playwright/test";
import { hasE2ECredentials, login } from "./auth";

const mutationsAllowed = process.env.E2E_ALLOW_MUTATIONS === "1";

test.describe("admin workflows", () => {
  test.skip(!hasE2ECredentials || !mutationsAllowed, "Requires an isolated fixture environment and E2E_ALLOW_MUTATIONS=1.");
  test.beforeEach(async ({ page }) => login(page));

  test("device, incident, and threshold administration is available", async ({ page }) => {
    for (const [path, heading] of [["/devices", "Devices"], ["/incidents", "Incidents"], ["/thresholds", "Thresholds"]] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    }
  });
});
