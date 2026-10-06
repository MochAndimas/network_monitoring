"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

import { useAuth } from "@/features/auth/auth-provider";

export function useMyAccount() {
  const { user } = useAuth();
  const client = useQueryClient();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  useEffect(() => setFullName(user?.full_name ?? ""), [user?.full_name]);
  const refreshSession = () =>
    client.invalidateQueries({ queryKey: ["auth", "session"] });
  const saveProfile = useMutation({
    mutationFn: () =>
      apiFetch("/auth/me", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: fullName }),
      }),
    onSuccess: refreshSession,
  });
  const changePassword = useMutation({
    mutationFn: () =>
      apiFetch("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }),
    onSuccess: async () => {
      setCurrentPassword("");
      setNewPassword("");
      await refreshSession();
    },
  });
  return {
    user,
    fullName,
    setFullName,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    saveProfile,
    changePassword,
  };
}
