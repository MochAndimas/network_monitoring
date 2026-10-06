export type Account = {
  id: number;
  username: string;
  full_name: string;
  role: "admin" | "viewer";
  is_active: boolean;
  created_at: string;
  password_changed_at: string | null;
  disabled_reason: string | null;
};
export type AccountForm = {
  username: string;
  full_name: string;
  password: string;
  role: "admin" | "viewer";
  is_active: boolean;
  disabled_reason: string;
};
export const emptyForm: AccountForm = {
  username: "",
  full_name: "",
  password: "",
  role: "viewer",
  is_active: true,
  disabled_reason: "",
};
