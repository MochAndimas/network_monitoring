"use client";

import { PageHeader } from "@/components/ui/page-header";

import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ApiError } from "@/lib/api/client";

import { useMyAccount } from "./use-my-account";
export function ViewerAccountPage() {
  const {
    user,
    fullName,
    setFullName,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    saveProfile,
    changePassword,
  } = useMyAccount();
  const error = [saveProfile.error, changePassword.error].find(Boolean);
  const message =
    error instanceof ApiError || error instanceof Error ? error.message : null;
  return (
    <main className="app-page accounts-page">
      <PageHeader
        title="Akun Saya"
        description="Kelola profil dan keamanan akun Anda sendiri."
      />
      <MetricGrid columns={3}>
        <MetricCard label="Username" value={user?.username ?? "-"} />
        <MetricCard label="Role" value="Viewer" />
        <MetricCard label="Status" value="Aktif" />
      </MetricGrid>
      {message ? (
        <p className="form-error" role="alert">
          {message}
        </p>
      ) : null}
      <section className="two-column">
        <form
          className="device-form account-settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            saveProfile.mutate();
          }}
        >
          <h2>Profil</h2>
          <label>
            Username
            <input value={user?.username ?? ""} disabled />
          </label>
          <label>
            Nama lengkap
            <input
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={saveProfile.isPending}>
            {saveProfile.isPending ? "Menyimpan…" : "Simpan profil"}
          </button>
        </form>
        <form
          className="device-form account-settings-form"
          onSubmit={(event) => {
            event.preventDefault();
            changePassword.mutate();
          }}
        >
          <h2>Ubah password</h2>
          <label>
            Password saat ini
            <input
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            Password baru
            <input
              type="password"
              minLength={12}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <button type="submit" disabled={changePassword.isPending}>
            {changePassword.isPending ? "Menyimpan…" : "Ubah password"}
          </button>
        </form>
      </section>
    </main>
  );
}
