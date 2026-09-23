"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
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
  const isLoginPage = usePathname() === "/login";
  const queryClient = useQueryClient();
  const session = useQuery<SessionResponse | null>({
    queryKey: ["auth", "session"],
    queryFn: async ({ signal }) => {
      const response = await apiFetch<SessionResponse>("/auth/restore", { method: "POST", signal });
      setAccessToken(response.access_token);
      return response;
    },
    retry: false,
    enabled: !isLoginPage,
    staleTime: 5 * 60_000
  });

  useEffect(() => {
    const handleExpiredSession = () => {
      if (isLoginPage) return;
      setAccessToken(undefined);
      void queryClient.cancelQueries({ queryKey: ["auth", "session"] });
      queryClient.setQueryData(["auth", "session"], null);
      router.replace("/login?reason=session-expired");
    };
    window.addEventListener("network-monitoring:auth-expired", handleExpiredSession);
    return () => window.removeEventListener("network-monitoring:auth-expired", handleExpiredSession);
  }, [isLoginPage, queryClient, router]);

  return (
    <AuthContext.Provider value={{
      user: session.data?.user,
      isRestoring: !isLoginPage && session.isPending,
      isAuthenticated: session.isSuccess && session.data !== null
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
