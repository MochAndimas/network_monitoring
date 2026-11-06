import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api/client";
import { fetchHealthData } from "./health-query";
vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });
describe("health requests", () => {
  it("cancels a stalled request after 30 seconds", async () => {
    vi.useFakeTimers();
    vi.mocked(apiFetch).mockImplementation((_path, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new Error("timeout")));
    }));
    const result = expect(fetchHealthData("/observability/summary", new AbortController().signal)).rejects.toThrow("timeout");
    await vi.advanceTimersByTimeAsync(30_000);
    await result;
    expect(vi.getTimerCount()).toBe(0);
  });
  it("cleans up the timer after success", async () => {
    vi.useFakeTimers();
    vi.mocked(apiFetch).mockResolvedValue({ database: "up" });
    await expect(fetchHealthData("/observability/summary", new AbortController().signal)).resolves.toEqual({ database: "up" });
    expect(vi.getTimerCount()).toBe(0);
  });
});
