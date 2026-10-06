"use client";

import { formatWib } from "@/lib/formatters";
import { PageHeader } from "@/components/ui/page-header";
import { MetaStrip } from "@/components/ui/meta-strip";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { CsvExport } from "@/components/ui/csv-export";
import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessLabel } from "@/components/ui/freshness-label";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { PermissionGate } from "@/components/ui/permission-gate";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { DeviceForm } from "./device-form";
import { DeviceImport } from "./device-import";
import type { Device } from "./types";

import { useDeviceFilters } from "./use-device-filters";
import {
  DEVICE_PAGE_LIMIT as LIMIT,
  useDeviceManagement,
} from "./use-device-management";
export function DevicesPage() {
  const filters = useDeviceFilters();
  const {
    tab,
    setTab,
    search,
    setSearch,
    type,
    setType,
    status,
    setStatus,
    activeOnly,
    setActiveOnly,
    offset,
    setOffset,
    resetPage,
  } = filters;
  const {
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
    refreshDevices,
  } = useDeviceManagement(filters);
  if (devices.isPending || types.isPending) return <LoadingState />;
  if (devices.isError)
    return (
      <ErrorState
        message="Inventaris device tidak dapat dimuat."
        onRetry={() => void devices.refetch()}
      />
    );
  const rows = devices.data.items;
  const counts = summary.data ?? {};
  const deviceTypes = types.data ?? [];
  return (
    <main className="app-page devices-page">
      <PageHeader
        className="devices-header"
        title="Devices"
        description="Inventory perangkat, status terkini, dan konfigurasi monitoring dalam satu workspace."
      />
      <MetaStrip
        items={[
          { label: "Total hasil", value: devices.data.meta.total ?? "—" },
          { label: "Mode pembaruan", value: "Manual" },
          {
            label: "Terakhir dimuat",
            value: formatWib(new Date().toISOString()),
          },
        ]}
      />
      <div className="devices-workspace-bar">
        <div
          className="devices-tabs"
          role="tablist"
          aria-label="Mode halaman devices"
        >
          <button
            className={tab === "inventory" ? "tab-active" : ""}
            onClick={() => setTab("inventory")}
            role="tab"
            aria-selected={tab === "inventory"}
          >
            Inventory
          </button>
          <PermissionGate>
            <button
              className={tab === "manage" ? "tab-active" : ""}
              onClick={() => setTab("manage")}
              role="tab"
              aria-selected={tab === "manage"}
            >
              Kelola device
            </button>
          </PermissionGate>
        </div>
        <p>
          {tab === "manage"
            ? "Perubahan inventory diterapkan langsung ke monitoring."
            : "Status diambil dari pemeriksaan terakhir setiap device."}
        </p>
      </div>
      <MetricGrid>
        {[
          ["Total inventory", counts.total ?? devices.data.meta.total ?? 0],
          ["Aktif dipantau", counts.active ?? 0],
          ["Butuh perhatian", (counts.down ?? 0) + (counts.warning ?? 0)],
          [
            "Tidak aktif",
            Math.max(
              0,
              (counts.total ?? devices.data.meta.total ?? 0) -
                (counts.active ?? 0),
            ),
          ],
        ].map(([label, value]) => (
          <MetricCard
            key={String(label)}
            label={String(label)}
            value={String(value)}
          />
        ))}
      </MetricGrid>
      <section className="devices-filter-panel" aria-label="Filter inventory">
        <div className="devices-filter-heading">
          <span>Temukan device</span>
          <small>Filter akan diterapkan ke tabel di bawah.</small>
        </div>
        <div className="filter-panel">
          <label>
            Cari
            <input
              value={search}
              placeholder="Nama, IP, site, atau lokasi"
              onChange={(event) => {
                setSearch(event.target.value);
                resetPage();
              }}
            />
          </label>
          <label>
            Tipe
            <select
              value={type}
              onChange={(event) => {
                setType(event.target.value);
                resetPage();
              }}
            >
              <option value="">Semua tipe</option>
              {deviceTypes.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                resetPage();
              }}
            >
              <option value="">Semua status</option>
              {["up", "warning", "down", "error", "unknown"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox">
            Hanya aktif
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(event) => {
                setActiveOnly(event.target.checked);
                resetPage();
              }}
            />
          </label>
        </div>
      </section>
      <div className="devices-table-header">
        <div>
          <p className="section-caption">
            {tab === "manage" ? "Configuration workspace" : "Device directory"}
          </p>
          <h2>{tab === "manage" ? "Kelola Device" : "Inventory Device"}</h2>
          <span>
            {(devices.data.meta.total ?? 0).toLocaleString("id-ID")} device
            sesuai filter
          </span>
        </div>
        <div className="inline-actions">
          <CsvExport
            filename="devices.csv"
            columns={[
              "Nama",
              "IP",
              "Tipe",
              "Site",
              "Lokasi",
              "Status",
              "Freshness",
              "Aktif",
            ]}
            rows={rows.map((item) => [
              item.name,
              item.ip_address,
              item.device_type,
              item.site,
              item.location,
              item.latest_status,
              item.latest_checked_at,
              item.is_active ? "Ya" : "Tidak",
            ])}
          />
          {tab === "manage" ? (
            <button
              onClick={() => {
                setMutationError(undefined);
                setEditing("new");
              }}
            >
              Tambah device
            </button>
          ) : null}
        </div>
      </div>
      <DataTable
        columns={[
          { key: "name", label: "Nama", render: (item) => item.name },
          { key: "ip", label: "IP", render: (item) => item.ip_address },
          { key: "type", label: "Tipe", render: (item) => item.device_type },
          { key: "site", label: "Site", render: (item) => item.site ?? "-" },
          {
            key: "location",
            label: "Lokasi",
            render: (item) => item.location ?? "-",
          },
          {
            key: "status",
            label: "Status terakhir",
            render: (item) => <StatusBadge value={item.latest_status} />,
          },
          {
            key: "fresh",
            label: "Freshness",
            render: (item) => (
              <FreshnessLabel checkedAt={item.latest_checked_at} />
            ),
          },
          {
            key: "active",
            label: "Aktif",
            render: (item) => (item.is_active ? "Ya" : "Tidak"),
          },
          ...(tab === "manage"
            ? [
                {
                  key: "actions",
                  label: "Aksi",
                  render: (item: Device) => (
                    <div className="inline-actions">
                      <button
                        className="button-secondary"
                        onClick={() => {
                          setMutationError(undefined);
                          setEditing(item);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="button-danger"
                        onClick={() => {
                          setMutationError(undefined);
                          setDeleting(item);
                        }}
                      >
                        Hapus
                      </button>
                    </div>
                  ),
                },
              ]
            : []),
        ]}
        rows={rows}
        pageSize={null}
      />
      <Pagination
        offset={offset}
        limit={LIMIT}
        total={devices.data.meta.total}
        onChange={setOffset}
      />
      {tab === "manage" ? (
        <PermissionGate>
          <DeviceImport
            types={deviceTypes}
            existingIps={
              new Set(
                allDevices.data?.items.map((item) => item.ip_address) ?? [],
              )
            }
            onComplete={async () => {
              await refreshDevices();
            }}
          />
        </PermissionGate>
      ) : null}
      {editing ? (
        <div className="dialog-backdrop">
          <section className="dialog" role="dialog" aria-modal="true">
            <h2>
              {editing === "new" ? "Tambah Device" : `Edit ${editing.name}`}
            </h2>
            <DeviceForm
              device={editing === "new" ? undefined : editing}
              types={deviceTypes}
              pending={save.isPending}
              error={mutationError}
              onSubmit={saveDevice}
              onCancel={() => setEditing(null)}
            />
          </section>
        </div>
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title="Hapus device"
          confirmLabel="Hapus device"
          pending={remove.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => void remove.mutateAsync(deleting)}
        >
          <p>
            Hapus <strong>{deleting.name}</strong>? Tindakan ini tidak dapat
            dibatalkan.
          </p>
          {mutationError ? <p className="form-error">{mutationError}</p> : null}
        </ConfirmDialog>
      ) : null}
    </main>
  );
}
