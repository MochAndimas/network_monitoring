import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, setAccessToken } from "@/lib/api/client";
import { AuthProvider, useAuth } from "./auth-provider";

const navigation = vi.hoisted(() => ({ pathname: "/login", router: { replace: vi.fn() } }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname, useRouter: () => navigation.router }));
vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn(), setAccessToken: vi.fn() }));

function SessionState() {
  const auth = useAuth();
  return <p>{auth.isRestoring ? "restoring" : auth.isAuthenticated ? "authenticated" : "anonymous"}</p>;
}

let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  navigation.pathname = "/login";
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => client.clear());

function mount() {
  return render(<QueryClientProvider client={client}><AuthProvider><SessionState /></AuthProvider></QueryClientProvider>);
}

describe("session lifecycle", () => {
  it("does not restore or redirect while the login form is active", () => {
    mount();
    act(() => window.dispatchEvent(new Event("network-monitoring:auth-expired")));
    expect(screen.getByText("anonymous")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  it("clears an expired session without restarting the active restore query", async () => {
    navigation.pathname = "/alerts";
    vi.mocked(apiFetch).mockResolvedValue({ user: { id: 1, username: "fixture" }, access_token: "fixture-token" });
    mount();
    expect(await screen.findByText("authenticated")).toBeInTheDocument();
    act(() => window.dispatchEvent(new Event("network-monitoring:auth-expired")));
    await waitFor(() => expect(screen.getByText("anonymous")).toBeInTheDocument());
    expect(client.getQueryData(["auth", "session"])).toBeNull();
    expect(setAccessToken).toHaveBeenLastCalledWith(undefined);
    expect(navigation.router.replace).toHaveBeenCalledWith("/login?reason=session-expired");
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith("/auth/restore", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });
});
