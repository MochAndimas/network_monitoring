"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { apiFetch, setAccessToken } from "@/lib/api/client";

type SessionUser = {
  username: string;
  full_name: string;
  role: "admin" | "viewer";
  expires_at: string;
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
