"use client";

import { AppShell } from "@/components/layout/app-shell";
import { ErrorState } from "@/components/ui/page-state";
import { useAuth } from "@/features/auth/auth-provider";
import { RequireAuth } from "@/features/auth/require-auth";

function RoleGate({ children, adminOnly }: Readonly<{ children: React.ReactNode; adminOnly: boolean }>) {
  const { user } = useAuth();
  if (adminOnly && user?.role !== "admin") return <ErrorState message="Halaman ini hanya tersedia untuk administrator." />;
  return <>{children}</>;
}

export function ProtectedPage({ children, adminOnly = false }: Readonly<{ children: React.ReactNode; adminOnly?: boolean }>) {
  return <RequireAuth><AppShell><RoleGate adminOnly={adminOnly}>{children}</RoleGate></AppShell></RequireAuth>;
}
