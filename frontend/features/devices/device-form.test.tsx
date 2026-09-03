import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeviceForm } from "./device-form";

describe("DeviceForm", () => {
  it("submits normalized optional fields", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<DeviceForm pending={false} error={undefined} onSubmit={onSubmit} onCancel={vi.fn()} types={[{ value: "mikrotik", label: "MikroTik" }]} />);

    fireEvent.change(screen.getByLabelText("Nama"), { target: { value: "Router Utama" } });
    fireEvent.change(screen.getByLabelText("IP address"), { target: { value: "192.168.1.1" } });
    fireEvent.change(screen.getByLabelText("Tipe"), { target: { value: "mikrotik" } });
    fireEvent.change(screen.getByLabelText("Site"), { target: { value: "Jakarta" } });
    fireEvent.submit(screen.getByRole("button", { name: "Tambah device" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ name: "Router Utama", ip_address: "192.168.1.1", device_type: "mikrotik", site: "Jakarta", location: null, description: null, is_active: true }));
  });
});
