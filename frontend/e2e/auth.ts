import { expect, type Page } from "@playwright/test";

export const hasE2ECredentials = Boolean(process.env.E2E_USERNAME && process.env.E2E_PASSWORD);

export async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.E2E_USERNAME ?? "");
  await page.getByLabel("Password").fill(process.env.E2E_PASSWORD ?? "");
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page).toHaveURL(/\/$/);
}
