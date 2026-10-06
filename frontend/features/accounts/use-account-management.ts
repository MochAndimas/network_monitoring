"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

import { useAuth } from "@/features/auth/auth-provider";

import { emptyForm, type Account, type AccountForm } from "./types";
export function useAccountManagement() {
  const { user } = useAuth();
  const client = useQueryClient();
  const accounts = useQuery({
    queryKey: ["admin", "users"],
    queryFn: ({ signal }) =>
      apiFetch<Account[]>("/auth/admin/users", { signal }),
    enabled: user?.role === "admin",
  });
  const [form, setForm] = useState<AccountForm>(emptyForm);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const [resetting, setResetting] = useState<Account | null>(null);
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["admin", "users"] });
  const create = useMutation({
    mutationFn: () =>
      apiFetch<Account>("/auth/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: form.username,
          full_name: form.full_name,
          password: form.password,
          role: form.role,
        }),
      }),
    onSuccess: () => {
      setCreating(false);
      setForm(emptyForm);
      return refresh();
    },
  });
  const update = useMutation({
    mutationFn: () =>
      editing
        ? apiFetch<Account>(`/auth/admin/users/${editing.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              full_name: form.full_name,
              role: form.role,
              is_active: form.is_active,
              disabled_reason: form.disabled_reason || null,
            }),
          })
        : Promise.reject(new Error("Akun tidak dipilih")),
    onSuccess: () => {
      setEditing(null);
      setForm(emptyForm);
      return refresh();
    },
  });
  const resetPassword = useMutation({
    mutationFn: () =>
      resetting
        ? apiFetch<Account>(
            `/auth/admin/users/${resetting.id}/reset-password`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ new_password: form.password }),
            },
          )
        : Promise.reject(new Error("Akun tidak dipilih")),
    onSuccess: () => {
      setResetting(null);
      setForm(emptyForm);
      return refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      deleting
        ? apiFetch<void>(`/auth/admin/users/${deleting.id}`, {
            method: "DELETE",
          })
        : Promise.reject(new Error("Akun tidak dipilih")),
    onSuccess: () => {
      setDeleting(null);
      return refresh();
    },
  });
  const openEdit = (account: Account) => {
    setEditing(account);
    setForm({
      username: account.username,
      full_name: account.full_name,
      password: "",
      role: account.role,
      is_active: account.is_active,
      disabled_reason: account.disabled_reason ?? "",
    });
  };
  return {
    user,
    accounts,
    form,
    setForm,
    creating,
    setCreating,
    editing,
    setEditing,
    deleting,
    setDeleting,
    resetting,
    setResetting,
    create,
    update,
    resetPassword,
    remove,
    openEdit,
  };
}
