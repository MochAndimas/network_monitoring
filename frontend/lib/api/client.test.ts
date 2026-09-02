import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, setAccessToken, withQuery } from "./client";

afterEach(() => {
  setAccessToken(undefined);
  vi.unstubAllGlobals();
});

describe("withQuery", () => {
  it("serializes supported values while omitting empty filters", () => {
    expect(withQuery("/metrics", { status: "warning", offset: 20, active: false, empty: "", missing: undefined, metrics: ["ping", "jitter"] })).toBe("/metrics?status=warning&offset=20&active=false&metrics=ping&metrics=jitter");
  });
});

describe("apiFetch", () => {
  it("sends JSON accept header, cookie credentials, and in-memory authorization", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("session-token");

    await expect(apiFetch<{ ok: boolean }>("/health")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/health", expect.objectContaining({ credentials: "include", headers: { Accept: "application/json", Authorization: "Bearer session-token" } }));
  });

  it("normalizes backend validation messages into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: "Nilai harus positif" }, { msg: "Scope wajib diisi" }] }), { status: 422, headers: { "Content-Type": "application/json" } })));
    await expect(apiFetch("/thresholds")).rejects.toMatchObject({ status: 422, message: "Nilai harus positif, Scope wajib diisi" });
  });

  it("clears expired auth and emits a session-expired event", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Sesi berakhir" }), { status: 401, headers: { "Content-Type": "application/json" } })));
    const expired = vi.fn(); window.addEventListener("network-monitoring:auth-expired", expired);
    setAccessToken("expired-token");
    await expect(apiFetch("/auth/check")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    window.removeEventListener("network-monitoring:auth-expired", expired);
  });
});
