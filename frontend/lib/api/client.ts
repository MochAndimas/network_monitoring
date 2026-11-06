const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001").replace(/\/$/, "");
let accessToken: string | undefined;
let refreshInFlight: Promise<boolean> | undefined;

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
  const request = () => fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { Accept: "application/json", ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...init.headers }
  });
  const requestedToken = accessToken;
  let response = await request();
  // Authentication endpoints must not recursively restore a session.
  if (response.status === 401 && !path.startsWith("/auth/")) {
    if (accessToken && accessToken !== requestedToken) {
      response = await request();
    } else {
      if (!refreshInFlight) {
        refreshInFlight = fetch(`${API_URL}/auth/restore`, {
          method: "POST", credentials: "include", headers: { Accept: "application/json" }
        }).then(async (restored) => {
          if (restored.status === 401) return false;
          if (!restored.ok) throw new ApiError("Sesi belum bisa diperbarui. Coba lagi.", restored.status);
          const body = await restored.json() as { access_token: string };
          setAccessToken(body.access_token);
          return true;
        }).finally(() => { refreshInFlight = undefined; });
      }
      if (await refreshInFlight) response = await request();
    }
  }
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
