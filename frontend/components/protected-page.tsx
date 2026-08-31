"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { AppShell } from "@/components/app-shell";

export function ProtectedPage({ title, description }: { title: string; description: string }) {
  const { ready, user } = useAuth(); const router = useRouter();
  useEffect(() => { if (ready && !user) router.replace("/login"); }, [ready, user, router]);
  if (!ready || !user) return <div className="login">Memulihkan sesi…</div>;
  return <AppShell><h1 className="page-title">{title}</h1><p className="page-description">{description}</p><section className="panel">Tahap berikutnya akan memigrasikan fitur Streamlit halaman ini dengan API FastAPI yang sama.</section></AppShell>;
}
