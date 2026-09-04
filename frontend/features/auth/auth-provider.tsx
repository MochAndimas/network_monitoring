"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, setAccessToken } from "@/lib/api/client";

type SessionUser = {
  id: number;
  username: string;
  full_name: string;
  role: "admin" | "viewer";
  expires_at: string;
  session_expires_at: string;
};

type SessionResponse = {
  user: SessionUser;
  access_token: string;
};

type AuthContextValue = {
  user: SessionUser | undefined;
  isRestoring: boolean;
  isAuthenticated: boolean;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: async () => {
      const response = await apiFetch<SessionResponse>("/auth/restore", { method: "POST" });
      setAccessToken(response.access_token);
      return response;
    },
    retry: false,
    staleTime: 5 * 60_000
  });

  useEffect(() => {
    const handleExpiredSession = () => {
      setAccessToken(undefined);
      queryClient.removeQueries({ queryKey: ["auth", "session"] });
      router.replace("/login?reason=session-expired");
    };
    window.addEventListener("network-monitoring:auth-expired", handleExpiredSession);
    return () => window.removeEventListener("network-monitoring:auth-expired", handleExpiredSession);
  }, [queryClient, router]);

  return (
    <AuthContext.Provider value={{
      user: session.data?.user,
      isRestoring: session.isPending,
      isAuthenticated: session.isSuccess
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
