import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { withQuery } from "./client";

let client: typeof import("./client");

beforeEach(async () => {
  // API_URL is resolved at module load. Each test owns its environment and token.
  vi.stubEnv("NEXT_PUBLIC_API_URL", undefined);
  vi.resetModules();
  client = await import("./client");
});

afterEach(() => {
  client.setAccessToken(undefined);
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("withQuery", () => {
  it("serializes supported values while omitting empty filters", () => {
    expect(withQuery("/metrics", { status: "warning", offset: 20, active: false, empty: "", missing: undefined, metrics: ["ping", "jitter"] })).toBe("/metrics?status=warning&offset=20&active=false&metrics=ping&metrics=jitter");
  });
});

describe("apiFetch", () => {
  it.each([
    [undefined, "http://localhost:8000/health"],
    ["https://api.example.test", "https://api.example.test/health"],
    ["https://api.example.test/", "https://api.example.test/health"],
  ])("uses the configured API URL %s", async (configuredUrl, expectedUrl) => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", configuredUrl);
    vi.resetModules();
    client = await import("./client");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await client.apiFetch("/health");

    expect(fetchMock).toHaveBeenCalledWith(expectedUrl, expect.any(Object));
  });

  it("sends JSON accept header, cookie credentials, and in-memory authorization", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    client.setAccessToken("session-token");

    await expect(client.apiFetch<{ ok: boolean }>("/health")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/health", expect.objectContaining({ credentials: "include", headers: { Accept: "application/json", Authorization: "Bearer session-token" } }));
  });

  it("normalizes backend validation messages into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: "Nilai harus positif" }, { msg: "Scope wajib diisi" }] }), { status: 422, headers: { "Content-Type": "application/json" } })));
    await expect(client.apiFetch("/thresholds")).rejects.toMatchObject({ status: 422, message: "Nilai harus positif, Scope wajib diisi" });
  });

  it("clears expired auth and emits a session-expired event", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Sesi berakhir" }), { status: 401, headers: { "Content-Type": "application/json" } })));
    const expired = vi.fn(); window.addEventListener("network-monitoring:auth-expired", expired);
    client.setAccessToken("expired-token");
    await expect(client.apiFetch("/auth/check")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    window.removeEventListener("network-monitoring:auth-expired", expired);
  });
});
