const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
let accessToken: string | undefined;

/** Keep the session token in memory only; browser cookies remain the refresh mechanism. */
export function setAccessToken(token: string | undefined) {
  accessToken = token;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly detail?: unknown) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { Accept: "application/json", ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...init.headers }
  });
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      setAccessToken(undefined);
      window.dispatchEvent(new Event("network-monitoring:auth-expired"));
    }
    const body = await response.json().catch(() => null) as { detail?: string | { msg?: string }[] } | null;
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((item) => item.msg ?? "Input tidak valid").join(", ") : `Request gagal (HTTP ${response.status})`;
    throw new ApiError(message, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function withQuery(path: string, values: Record<string, string | number | boolean | readonly string[] | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (Array.isArray(value)) value.filter(Boolean).forEach((item) => query.append(key, item));
    else if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `${path}?${serialized}` : path;
}
