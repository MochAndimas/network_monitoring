import { AppShell } from "@/components/layout/app-shell";
import { RequireAuth } from "@/features/auth/require-auth";

export function ProtectedPage({ children }: Readonly<{ children: React.ReactNode }>) {
  return <RequireAuth><AppShell>{children}</AppShell></RequireAuth>;
}
