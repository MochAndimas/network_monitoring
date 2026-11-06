import { apiFetch } from "@/lib/api/client";

/** Bound dashboard requests and release timers/listeners after every outcome. */
export async function fetchHealthData<T>(path: string, signal: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason);
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  const timer = setTimeout(() => controller.abort(new Error("System Health timeout")), 30_000);
  try {
    return await apiFetch<T>(path, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
  }
}
