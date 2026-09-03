import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./confirm-dialog";

describe("ConfirmDialog", () => {
  it("exposes an accessible confirmation flow", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmDialog title="Hapus device" confirmLabel="Hapus" onConfirm={onConfirm} onClose={onClose}>Aksi ini tidak dapat dibatalkan.</ConfirmDialog>);

    expect(screen.getByRole("dialog", { name: "Hapus device" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hapus" }));
    fireEvent.click(screen.getByRole("button", { name: "Batal" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("prevents duplicate actions while pending", () => {
    const { getByRole } = render(<ConfirmDialog title="Hapus device" pending onConfirm={vi.fn()} onClose={vi.fn()}>Memproses perubahan.</ConfirmDialog>);
    expect(getByRole("button", { name: "Memproses…" })).toBeDisabled();
    expect(getByRole("button", { name: "Batal" })).toBeDisabled();
  });
});
