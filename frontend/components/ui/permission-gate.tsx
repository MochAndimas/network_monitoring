import { ReactNode } from "react";
import { useAuth } from "@/features/auth/auth-provider";

export function PermissionGate({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const { user } = useAuth();
  return user?.role === "admin" ? <>{children}</> : <>{fallback}</>;
}
