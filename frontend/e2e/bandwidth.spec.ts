import { expect, test, type Page } from "@playwright/test";

/** Fully synthetic API responses: never requires credentials or a running backend. */
async function fixture(page: Page) {
  const calls: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const row = {
    day: "2026-10-15",
    subject: "c:10",
    client_id: 10,
    display_name: "Office Laptop",
    unresolved_ip: null,
    upload_bytes: "104857600",
    download_bytes: "419430400",
    total_bytes: "524288000",
    estimated_bytes: "10485760",
    unresolved_bytes: "0",
    updated_ns: "1791997200000000001",
  };
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (
      !/^\/(auth|bandwidth|metrics|observability)\//.test(path) &&
      path !== "/devices/options"
    )
      return route.continue();
    const headers = {
      "Access-Control-Allow-Origin":
        request.headers().origin ?? new URL(page.url()).origin,
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Headers": "authorization,content-type",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    };
    if (request.method() === "OPTIONS")
      return route.fulfill({ status: 204, headers });
    calls.push(path + url.search);
    let data: unknown;
    if (path === "/auth/restore")
      data = {
        access_token: "synthetic-bandwidth-token",
        user: {
          id: 1,
          username: "synthetic-viewer",
          full_name: "Bandwidth Test",
          role: "viewer",
          expires_at: "2030-01-01T00:00:00Z",
          session_expires_at: "2030-01-01T00:00:00Z",
        },
      };
    else if (path === "/devices/options")
      data = [
        {
          id: 1,
          name: "MikroTik Office",
          ip_address: "192.0.2.1",
          device_type: "mikrotik",
        },
        {
          id: 2,
          name: "MikroTik Branch",
          ip_address: "192.0.2.2",
          device_type: "mikrotik",
        },
      ];
    else if (path.endsWith("/clients"))
      data = {
        items: [
          {
            id: 10,
            display_name: "Office Laptop",
            mac_address: "02:00:00:00:00:01",
            hostname: "office-laptop",
            custom_name: "Office Laptop",
            first_seen_ns: row.updated_ns,
            last_seen_ns: row.updated_ns,
          },
        ],
        next_after_id: null,
      };
    else if (path.includes("/usage/"))
      data = {
        router_id: path.includes("/2/") ? 2 : 1,
        start: url.searchParams.get("start"),
        end: url.searchParams.get("end"),
        timezone: "Asia/Jakarta",
        allocation: "proportional_integer_v1",
        completeness: "unverified",
        items: [row],
        limit: 10,
        offset: 0,
        has_more: false,
      };
    else {
      errors.push(`Unexpected API call: ${path}`);
      return route.fulfill({
        status: 500,
        headers,
        body: "Unexpected synthetic API request",
      });
    }
    return route.fulfill({
      status: 200,
      headers,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
  return { calls, errors };
}

test("bandwidth URL filters and router isolation work without health metrics", async ({
  page,
}) => {
  const { calls, errors } = await fixture(page);
  await page.goto(
    "/live-monitoring?tab=bandwidth&device=1&bw_from=2026-10-14&bw_to=2026-10-15",
  );
  const top = page.getByRole("region", {
    name: "Top pengguna · Semua perangkat",
  });
  await top.getByRole("button", { name: "Office Laptop", exact: true }).click();
  await expect(page).toHaveURL(/bw_client=10/);
  await expect(
    page.getByRole("heading", { name: "Penggunaan harian · Office Laptop" }),
  ).toBeVisible();
  const dialog = page.getByRole("dialog", {
    name: "Detail bandwidth · Office Laptop",
  });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page).not.toHaveURL(/bw_client=/);
  await expect(
    top.getByRole("button", { name: "Office Laptop", exact: true }),
  ).toBeFocused();
  await page.getByLabel("Router MikroTik").selectOption("2");
  await expect(page).toHaveURL(/device=2/);
  await expect(page).not.toHaveURL(/bw_client=/);
  await expect(
    page.getByRole("heading", { name: "Penggunaan harian · Semua perangkat" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      calls.some((path) => path.startsWith("/bandwidth/2/usage/daily")),
    )
    .toBe(true);
  expect(
    calls
      .filter((path) => path.startsWith("/bandwidth/2/"))
      .every((path) => !path.includes("client_id")),
  ).toBe(true);
  expect(calls.some((path) => path.startsWith("/metrics/"))).toBe(false);
  expect(errors).toEqual([]);
});

test("bandwidth remains usable at mobile width in both themes", async ({
  page,
}, testInfo) => {
  const { errors } = await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(
    "/live-monitoring?tab=bandwidth&device=1&bw_from=2026-10-14&bw_to=2026-10-15",
  );
  await expect(page.getByText("Total tercatat", { exact: true })).toBeVisible();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const title = page.getByRole("heading", {
      name: "Penggunaan harian · Semua perangkat",
    });
    await title.scrollIntoViewIfNeeded();
    await expect(title).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`bandwidth-${theme}-mobile.png`),
      animations: "disabled",
    });
  }
  expect(errors).toEqual([]);
});
