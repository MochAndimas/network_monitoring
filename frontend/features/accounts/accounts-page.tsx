"use client";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ApiError } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";

import { emptyForm } from "./types";
import { useAccountManagement } from "./use-account-management";
import { AccountFormDialog } from "./account-form-dialog";
import { ViewerAccountPage } from "./viewer-account-page";
export function AccountsPage() {
  const {
    user,
    accounts,
    form,
    setForm,
    creating,
    setCreating,
    editing,
    setEditing,
    deleting,
    setDeleting,
    resetting,
    setResetting,
    create,
    update,
    resetPassword,
    remove,
    openEdit,
  } = useAccountManagement();
  if (user?.role !== "admin") return <ViewerAccountPage />;
  if (accounts.isPending) return <LoadingState />;
  if (accounts.isError)
    return (
      <ErrorState
        message="Daftar akun tidak dapat dimuat."
        onRetry={() => void accounts.refetch()}
      />
    );
  const error = [
    create.error,
    update.error,
    resetPassword.error,
    remove.error,
  ].find(Boolean);
  const message =
    error instanceof ApiError || error instanceof Error ? error.message : null;
  return (
    <main className="app-page accounts-page">
      <PageHeader
        title="Kelola Akun"
        description="Buat, ubah, nonaktifkan, atau hapus akun operator dashboard."
        actions={
          <button
            type="button"
            onClick={() => {
              setCreating(true);
              setEditing(null);
              setForm(emptyForm);
            }}
          >
            Tambah akun
          </button>
        }
      />
      <MetricGrid columns={3}>
        <MetricCard label="Total akun" value={accounts.data.length} />
        <MetricCard
          label="Administrator"
          value={
            accounts.data.filter((account) => account.role === "admin").length
          }
        />
        <MetricCard
          label="Akun aktif"
          value={accounts.data.filter((account) => account.is_active).length}
        />
      </MetricGrid>
      {message ? (
        <p className="form-error" role="alert">
          {message}
        </p>
      ) : null}
      <DataTable
        columns={[
          {
            key: "account",
            label: "Akun",
            render: (account) => (
              <span className="account-table-identity">
                <strong>{account.full_name}</strong>
                <small>@{account.username}</small>
              </span>
            ),
          },
          {
            key: "role",
            label: "Role",
            render: (account) => <StatusBadge value={account.role} />,
          },
          {
            key: "status",
            label: "Status",
            render: (account) => (
              <StatusBadge value={account.is_active ? "active" : "inactive"} />
            ),
          },
          {
            key: "created",
            label: "Dibuat",
            render: (account) => formatWib(account.created_at),
          },
          {
            key: "action",
            label: "Aksi",
            render: (account) => (
              <div className="inline-actions">
                <button
                  className="button-secondary"
                  onClick={() => openEdit(account)}
                >
                  Edit
                </button>
                <button
                  className="button-secondary"
                  onClick={() => {
                    setResetting(account);
                    setForm(emptyForm);
                  }}
                >
                  Reset sandi
                </button>
                <button
                  className="button-danger"
                  disabled={account.username === user.username}
                  onClick={() => setDeleting(account)}
                >
                  Hapus
                </button>
              </div>
            ),
          },
        ]}
        rows={accounts.data}
        emptyLabel="Belum ada akun."
      />
      {creating || editing ? (
        <AccountFormDialog
          title={editing ? `Edit ${editing.username}` : "Tambah akun"}
          form={form}
          onChange={setForm}
          pending={create.isPending || update.isPending}
          onClose={() => {
            setCreating(false);
            setEditing(null);
            setForm(emptyForm);
          }}
          onSubmit={() => (editing ? update.mutate() : create.mutate())}
          editMode={Boolean(editing)}
        />
      ) : null}
      {resetting ? (
        <AccountFormDialog
          title={`Reset sandi ${resetting.username}`}
          form={form}
          onChange={setForm}
          pending={resetPassword.isPending}
          onClose={() => {
            setResetting(null);
            setForm(emptyForm);
          }}
          onSubmit={() => resetPassword.mutate()}
          passwordOnly
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={`Hapus akun ${deleting.username}?`}
          confirmLabel="Hapus permanen"
          pending={remove.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate()}
        >
          <p>
            Akun, sesi aktif, dan akses login miliknya akan dihapus permanen.
            Audit log tetap dipertahankan.
          </p>
        </ConfirmDialog>
      ) : null}
    </main>
  );
}
