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
    [undefined, "http://localhost:3001/health"],
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
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:3001/health", expect.objectContaining({ credentials: "include", headers: { Accept: "application/json", Authorization: "Bearer session-token" } }));
  });

  it("normalizes backend validation messages into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: "Nilai harus positif" }, { msg: "Scope wajib diisi" }] }), { status: 422, headers: { "Content-Type": "application/json" } })));
    await expect(client.apiFetch("/thresholds")).rejects.toMatchObject({ status: 422, message: "Nilai harus positif, Scope wajib diisi" });
  });

  it("renews an expired access token before retrying the original request", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "renewed" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    client.setAccessToken("expired");
    await expect(client.apiFetch("/devices")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://localhost:3001/auth/restore", expect.objectContaining({ method: "POST", credentials: "include" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://localhost:3001/devices", expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer renewed" }) }));
  });

  it("shares restoration across simultaneous expired requests", async () => {
    let finishRestore!: (response: Response) => void;
    const restored = new Promise<Response>((resolve) => { finishRestore = resolve; });
    const fetchMock = vi.fn().mockImplementation((_url, init) => {
      if (_url.endsWith("/auth/restore")) return restored;
      if (init.headers.Authorization === "Bearer renewed") return Promise.resolve(new Response("{}", { status: 200 }));
      return Promise.resolve(new Response(null, { status: 401 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    client.setAccessToken("expired");
    const requests = [client.apiFetch("/devices"), client.apiFetch("/alerts")];
    await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/auth/restore"))).toHaveLength(1));
    finishRestore(new Response(JSON.stringify({ access_token: "renewed" }), { status: 200 }));
    await Promise.all(requests);
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/auth/restore"))).toHaveLength(1);
  });

  it("does not expire the session when restoration temporarily fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    const expired = vi.fn();
    window.addEventListener("network-monitoring:auth-expired", expired);
    await expect(client.apiFetch("/devices")).rejects.toMatchObject({ status: 503 });
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener("network-monitoring:auth-expired", expired);
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
