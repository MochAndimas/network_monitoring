import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PermissionGate } from "./permission-gate";

const { useAuth } = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("@/features/auth/auth-provider", () => ({ useAuth }));

describe("PermissionGate", () => {
  beforeEach(() => useAuth.mockReset());

  it("renders mutations only for administrators", () => {
    useAuth.mockReturnValue({ user: { role: "admin" } });
    render(<PermissionGate fallback={<span>Read-only</span>}><button>Mutasi</button></PermissionGate>);
    expect(screen.getByRole("button", { name: "Mutasi" })).toBeInTheDocument();
  });

  it("renders the read-only fallback for viewers", () => {
    useAuth.mockReturnValue({ user: { role: "viewer" } });
    render(<PermissionGate fallback={<span>Read-only</span>}><button>Mutasi</button></PermissionGate>);
    expect(screen.queryByRole("button", { name: "Mutasi" })).not.toBeInTheDocument();
    expect(screen.getByText("Read-only")).toBeInTheDocument();
  });
});
