"use client";

import { FormEvent, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api/client";

type LoginResponse = { user: { username: string; role: string }; access_token: string };

export function LoginPage() {
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setPending(true); setError(undefined);
    try {
      await apiFetch<LoginResponse>("/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: data.get("username"), password: data.get("password"), remember: data.get("remember") === "on" })
      });
      window.location.assign("/");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Login gagal. Coba lagi.");
    } finally { setPending(false); }
  }

  return <main className="login-page"><form className="login-card" onSubmit={submit}>
    <h1>Masuk Dashboard</h1><p>Masuk dengan akun backend monitoring untuk membuka dashboard.</p>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    <label>Username<input name="username" autoComplete="username" required /></label>
    <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
    <label className="checkbox"><input name="remember" type="checkbox" /> Tetap masuk selama 7 hari</label>
    <button type="submit" disabled={pending}>{pending ? "Memproses…" : "Masuk"}</button>
  </form></main>;
}
