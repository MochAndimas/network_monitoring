"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ApiError, apiFetch } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { useAuth } from "@/features/auth/auth-provider";

type Account = { id: number; username: string; full_name: string; role: "admin" | "viewer"; is_active: boolean; created_at: string; password_changed_at: string | null; disabled_reason: string | null };
type AccountForm = { username: string; full_name: string; password: string; role: "admin" | "viewer"; is_active: boolean; disabled_reason: string };
const emptyForm: AccountForm = { username: "", full_name: "", password: "", role: "viewer", is_active: true, disabled_reason: "" };

export function AccountsPage() {
  const { user } = useAuth();
  const client = useQueryClient();
  const accounts = useQuery({ queryKey: ["admin", "users"], queryFn: () => apiFetch<Account[]>("/auth/admin/users"), enabled: user?.role === "admin" });
  const [form, setForm] = useState<AccountForm>(emptyForm);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const [resetting, setResetting] = useState<Account | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: ["admin", "users"] });
  const create = useMutation({ mutationFn: () => apiFetch<Account>("/auth/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.username, full_name: form.full_name, password: form.password, role: form.role }) }), onSuccess: () => { setCreating(false); setForm(emptyForm); return refresh(); } });
  const update = useMutation({ mutationFn: () => editing ? apiFetch<Account>(`/auth/admin/users/${editing.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ full_name: form.full_name, role: form.role, is_active: form.is_active, disabled_reason: form.disabled_reason || null }) }) : Promise.reject(new Error("Akun tidak dipilih")), onSuccess: () => { setEditing(null); setForm(emptyForm); return refresh(); } });
  const resetPassword = useMutation({ mutationFn: () => resetting ? apiFetch<Account>(`/auth/admin/users/${resetting.id}/reset-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_password: form.password }) }) : Promise.reject(new Error("Akun tidak dipilih")), onSuccess: () => { setResetting(null); setForm(emptyForm); return refresh(); } });
  const remove = useMutation({ mutationFn: () => deleting ? apiFetch<void>(`/auth/admin/users/${deleting.id}`, { method: "DELETE" }) : Promise.reject(new Error("Akun tidak dipilih")), onSuccess: () => { setDeleting(null); return refresh(); } });
  if (user?.role !== "admin") return <ViewerAccountPage />;
  if (accounts.isPending) return <LoadingState />;
  if (accounts.isError) return <ErrorState message="Daftar akun tidak dapat dimuat." onRetry={() => void accounts.refetch()} />;
  const error = [create.error, update.error, resetPassword.error, remove.error].find(Boolean);
  const message = error instanceof ApiError || error instanceof Error ? error.message : null;
  const openEdit = (account: Account) => { setEditing(account); setForm({ username: account.username, full_name: account.full_name, password: "", role: account.role, is_active: account.is_active, disabled_reason: account.disabled_reason ?? "" }); };
  return <main className="app-page accounts-page"><PageHeader title="Kelola Akun" description="Buat, ubah, nonaktifkan, atau hapus akun operator dashboard." actions={<button type="button" onClick={() => { setCreating(true); setEditing(null); setForm(emptyForm); }}>Tambah akun</button>} />
    <MetricGrid columns={3}><MetricCard label="Total akun" value={accounts.data.length} /><MetricCard label="Administrator" value={accounts.data.filter((account) => account.role === "admin").length} /><MetricCard label="Akun aktif" value={accounts.data.filter((account) => account.is_active).length} /></MetricGrid>
    {message ? <p className="form-error" role="alert">{message}</p> : null}
    <DataTable columns={[{ key: "account", label: "Akun", render: (account) => <span className="account-table-identity"><strong>{account.full_name}</strong><small>@{account.username}</small></span> }, { key: "role", label: "Role", render: (account) => <StatusBadge value={account.role} /> }, { key: "status", label: "Status", render: (account) => <StatusBadge value={account.is_active ? "active" : "inactive"} /> }, { key: "created", label: "Dibuat", render: (account) => formatWib(account.created_at) }, { key: "action", label: "Aksi", render: (account) => <div className="inline-actions"><button className="button-secondary" onClick={() => openEdit(account)}>Edit</button><button className="button-secondary" onClick={() => { setResetting(account); setForm(emptyForm); }}>Reset sandi</button><button className="button-danger" disabled={account.username === user.username} onClick={() => setDeleting(account)}>Hapus</button></div> }]} rows={accounts.data} emptyLabel="Belum ada akun." />
    {creating || editing ? <AccountFormDialog title={editing ? `Edit ${editing.username}` : "Tambah akun"} form={form} onChange={setForm} pending={create.isPending || update.isPending} onClose={() => { setCreating(false); setEditing(null); setForm(emptyForm); }} onSubmit={() => editing ? update.mutate() : create.mutate()} editMode={Boolean(editing)} /> : null}
    {resetting ? <AccountFormDialog title={`Reset sandi ${resetting.username}`} form={form} onChange={setForm} pending={resetPassword.isPending} onClose={() => { setResetting(null); setForm(emptyForm); }} onSubmit={() => resetPassword.mutate()} passwordOnly /> : null}
    {deleting ? <ConfirmDialog title={`Hapus akun ${deleting.username}?`} confirmLabel="Hapus permanen" pending={remove.isPending} onClose={() => setDeleting(null)} onConfirm={() => remove.mutate()}><p>Akun, sesi aktif, dan akses login miliknya akan dihapus permanen. Audit log tetap dipertahankan.</p></ConfirmDialog> : null}
  </main>;
}

function AccountFormDialog({ title, form, onChange, pending, onClose, onSubmit, editMode = false, passwordOnly = false }: { title: string; form: AccountForm; onChange: (form: AccountForm) => void; pending: boolean; onClose: () => void; onSubmit: () => void; editMode?: boolean; passwordOnly?: boolean }) {
  return <div className="dialog-backdrop" role="presentation"><form className="dialog account-dialog" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}><h2>{title}</h2>{passwordOnly ? <label>Password baru<input type="password" minLength={12} value={form.password} onChange={(event) => onChange({ ...form, password: event.target.value })} required /></label> : <div className="device-form"><label>Nama lengkap<input value={form.full_name} onChange={(event) => onChange({ ...form, full_name: event.target.value })} required /></label>{!editMode ? <label>Username<input value={form.username} onChange={(event) => onChange({ ...form, username: event.target.value })} required /></label> : null}<label>Role<select value={form.role} onChange={(event) => onChange({ ...form, role: event.target.value as AccountForm["role"] })}><option value="viewer">Viewer</option><option value="admin">Administrator</option></select></label>{!editMode ? <label>Password<input type="password" minLength={12} value={form.password} onChange={(event) => onChange({ ...form, password: event.target.value })} required /></label> : null}{editMode ? <label className="checkbox">Akun aktif<input type="checkbox" checked={form.is_active} onChange={(event) => onChange({ ...form, is_active: event.target.checked })} /></label> : null}</div>}<footer><button className="button-secondary" type="button" onClick={onClose}>Batal</button><button type="submit" disabled={pending}>{pending ? "Menyimpan…" : passwordOnly ? "Reset sandi" : editMode ? "Simpan perubahan" : "Buat akun"}</button></footer></form></div>;
}

function ViewerAccountPage() {
  const { user } = useAuth();
  const client = useQueryClient();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  useEffect(() => setFullName(user?.full_name ?? ""), [user?.full_name]);
  const refreshSession = () => client.invalidateQueries({ queryKey: ["auth", "session"] });
  const saveProfile = useMutation({ mutationFn: () => apiFetch("/auth/me", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ full_name: fullName }) }), onSuccess: refreshSession });
  const changePassword = useMutation({ mutationFn: () => apiFetch("/auth/change-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }), onSuccess: async () => { setCurrentPassword(""); setNewPassword(""); await refreshSession(); } });
  const error = [saveProfile.error, changePassword.error].find(Boolean);
  const message = error instanceof ApiError || error instanceof Error ? error.message : null;
  return <main className="app-page accounts-page"><PageHeader title="Akun Saya" description="Kelola profil dan keamanan akun Anda sendiri." />
    <MetricGrid columns={3}><MetricCard label="Username" value={user?.username ?? "-"} /><MetricCard label="Role" value="Viewer" /><MetricCard label="Status" value="Aktif" /></MetricGrid>
    {message ? <p className="form-error" role="alert">{message}</p> : null}
    <section className="two-column"><form className="device-form account-settings-form" onSubmit={(event) => { event.preventDefault(); saveProfile.mutate(); }}><h2>Profil</h2><label>Username<input value={user?.username ?? ""} disabled /></label><label>Nama lengkap<input value={fullName} onChange={(event) => setFullName(event.target.value)} required /></label><button type="submit" disabled={saveProfile.isPending}>{saveProfile.isPending ? "Menyimpan…" : "Simpan profil"}</button></form><form className="device-form account-settings-form" onSubmit={(event) => { event.preventDefault(); changePassword.mutate(); }}><h2>Ubah password</h2><label>Password saat ini<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" required /></label><label>Password baru<input type="password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required /></label><button type="submit" disabled={changePassword.isPending}>{changePassword.isPending ? "Menyimpan…" : "Ubah password"}</button></form></section>
  </main>;
}
