export type Device = { id: number; name: string; ip_address: string; device_type: string; site: string | null; location: string | null; description: string | null; is_active: boolean; latest_status: string; latest_checked_at: string | null };
export type DevicePage = { items: Device[]; meta: { total: number | null; limit: number; offset: number; next_cursor?: string | null; has_more: boolean } };
export type DeviceDraft = Pick<Device, "name" | "ip_address" | "device_type" | "site" | "location" | "description" | "is_active">;
export type DeviceTypeOption = { value: string; label: string };
