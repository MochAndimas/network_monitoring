"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, ApiError, withQuery } from "@/lib/api/client";

import type {
  Device,
  DeviceDraft,
  DevicePage,
  DeviceTypeOption,
} from "./types";

import type { useDeviceFilters } from "./use-device-filters";
export const DEVICE_PAGE_LIMIT = 10;
const LIMIT = DEVICE_PAGE_LIMIT;
const invalidateDevices = (client: ReturnType<typeof useQueryClient>) =>
  client.invalidateQueries({ queryKey: ["devices"] });
export function useDeviceManagement({
  debouncedSearch,
  type,
  status,
  activeOnly,
  offset,
}: Pick<
  ReturnType<typeof useDeviceFilters>,
  "debouncedSearch" | "type" | "status" | "activeOnly" | "offset"
>) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Device | null | "new">(null);
  const [deleting, setDeleting] = useState<Device | null>(null);
  const [mutationError, setMutationError] = useState<string>();
  const devices = useQuery({
    queryKey: [
      "devices",
      { search: debouncedSearch, type, status, activeOnly, offset },
    ],
    queryFn: ({ signal }) =>
      apiFetch<DevicePage>(
        withQuery("/devices/paged", {
          search: debouncedSearch,
          device_type: type,
          latest_status: status,
          active_only: activeOnly,
          limit: LIMIT,
          offset,
        }),
        { signal },
      ),
  });
  const types = useQuery({
    queryKey: ["device-types"],
    queryFn: ({ signal }) =>
      apiFetch<DeviceTypeOption[]>("/devices/meta/types", { signal }),
    staleTime: Infinity,
  });
  const summary = useQuery({
    queryKey: ["device-summary"],
    queryFn: ({ signal }) =>
      apiFetch<Record<string, number>>("/devices/status-summary", { signal }),
  });
  const allDevices = useQuery({
    queryKey: ["devices", "import-options"],
    queryFn: ({ signal }) =>
      apiFetch<DevicePage>(
        withQuery("/devices/paged", { limit: 500, offset: 0 }),
        { signal },
      ),
  });
  const save = useMutation({
    mutationFn: ({
      device,
      draft,
    }: {
      device: Device | null | "new";
      draft: DeviceDraft;
    }) =>
      apiFetch<Device>(
        device && device !== "new" ? `/devices/${device.id}` : "/devices",
        {
          method: device && device !== "new" ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        },
      ),
    onSuccess: async () => {
      await invalidateDevices(queryClient);
      setEditing(null);
    },
    onError: (error) =>
      setMutationError(
        error instanceof ApiError ? error.message : "Gagal menyimpan device.",
      ),
  });
  const remove = useMutation({
    mutationFn: (device: Device) =>
      apiFetch<void>(`/devices/${device.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidateDevices(queryClient);
      setDeleting(null);
    },
    onError: (error) =>
      setMutationError(
        error instanceof ApiError ? error.message : "Gagal menghapus device.",
      ),
  });
  const saveDevice = async (draft: DeviceDraft) => {
    setMutationError(undefined);
    await save.mutateAsync({ device: editing, draft });
  };
  return {
    devices,
    types,
    summary,
    allDevices,
    save,
    remove,
    editing,
    setEditing,
    deleting,
    setDeleting,
    mutationError,
    setMutationError,
    saveDevice,
    refreshDevices: () => invalidateDevices(queryClient),
  };
}
