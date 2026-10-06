import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { useAccountManagement } from "./use-account-management";
import type { Account } from "./types";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn(), role: "admin" }));
vi.mock("@/lib/api/client", () => ({ apiFetch: mocks.apiFetch }));
vi.mock("@/features/auth/auth-provider", () => ({
  useAuth: () => ({ user: { username: "admin", role: mocks.role } }),
}));
const account: Account = {
  id: 2,
  username: "viewer",
  full_name: "Viewer",
  role: "viewer",
  is_active: true,
  disabled_reason: null,
  created_at: "2026-10-01",
  password_changed_at: null,
};
function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}
beforeEach(() => {
  mocks.role = "admin";
  mocks.apiFetch
    .mockReset()
    .mockImplementation((url) =>
      Promise.resolve(url === "/auth/admin/users" ? [account] : account),
    );
});
test("viewer never fetches administrator accounts", () => {
  mocks.role = "viewer";
  renderHook(() => useAccountManagement(), { wrapper: wrapper() });
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});
test("editing sends profile fields and clears dialog after successful refresh", async () => {
  const { result } = renderHook(() => useAccountManagement(), {
    wrapper: wrapper(),
  });
  await waitFor(() => expect(result.current.accounts.isSuccess).toBe(true));
  act(() => result.current.openEdit(account));
  act(() =>
    result.current.setForm({
      ...result.current.form,
      full_name: "Updated",
      password: "must not be sent",
    }),
  );
  await act(async () => {
    await result.current.update.mutateAsync();
  });
  const call = mocks.apiFetch.mock.calls.find(
    ([, options]) => options?.method === "PUT",
  )!;
  expect(call[0]).toBe("/auth/admin/users/2");
  expect(JSON.parse(call[1].body)).toEqual({
    full_name: "Updated",
    role: "viewer",
    is_active: true,
    disabled_reason: null,
  });
  expect(result.current.editing).toBeNull();
  expect(
    mocks.apiFetch.mock.calls.filter(([url]) => url === "/auth/admin/users")
      .length,
  ).toBeGreaterThan(1);
});
test("password reset targets the selected account and clears sensitive form state", async () => {
  const { result } = renderHook(() => useAccountManagement(), {
    wrapper: wrapper(),
  });
  await waitFor(() => expect(result.current.accounts.isSuccess).toBe(true));
  act(() => {
    result.current.setResetting(account);
    result.current.setForm({
      ...result.current.form,
      password: "fixture-pass-123",
    });
  });
  await act(async () => {
    await result.current.resetPassword.mutateAsync();
  });
  expect(mocks.apiFetch).toHaveBeenCalledWith(
    "/auth/admin/users/2/reset-password",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ new_password: "fixture-pass-123" }),
    }),
  );
  expect(result.current.resetting).toBeNull();
  expect(result.current.form.password).toBe("");
});
