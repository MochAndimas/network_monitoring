"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { LoadingState } from "@/components/ui/page-state";
import { useAuth } from "./auth-provider";

export function RequireAuth({ children }: Readonly<{ children: React.ReactNode }>) {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!auth.isRestoring && !auth.isAuthenticated) router.replace("/login");
  }, [auth.isAuthenticated, auth.isRestoring, router]);

  if (!auth.isAuthenticated) return <LoadingState label="Memeriksa sesi…" />;
  return <>{children}</>;
}
