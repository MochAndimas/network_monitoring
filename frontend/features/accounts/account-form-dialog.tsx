"use client";
import type { AccountForm } from "./types";
export function AccountFormDialog({
  title,
  form,
  onChange,
  pending,
  onClose,
  onSubmit,
  editMode = false,
  passwordOnly = false,
}: {
  title: string;
  form: AccountForm;
  onChange: (form: AccountForm) => void;
  pending: boolean;
  onClose: () => void;
  onSubmit: () => void;
  editMode?: boolean;
  passwordOnly?: boolean;
}) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <form
        className="dialog account-dialog"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <h2>{title}</h2>
        {passwordOnly ? (
          <label>
            Password baru
            <input
              type="password"
              minLength={12}
              value={form.password}
              onChange={(event) =>
                onChange({ ...form, password: event.target.value })
              }
              required
            />
          </label>
        ) : (
          <div className="device-form">
            <label>
              Nama lengkap
              <input
                value={form.full_name}
                onChange={(event) =>
                  onChange({ ...form, full_name: event.target.value })
                }
                required
              />
            </label>
            {!editMode ? (
              <label>
                Username
                <input
                  value={form.username}
                  onChange={(event) =>
                    onChange({ ...form, username: event.target.value })
                  }
                  required
                />
              </label>
            ) : null}
            <label>
              Role
              <select
                value={form.role}
                onChange={(event) =>
                  onChange({
                    ...form,
                    role: event.target.value as AccountForm["role"],
                  })
                }
              >
                <option value="viewer">Viewer</option>
                <option value="admin">Administrator</option>
              </select>
            </label>
            {!editMode ? (
              <label>
                Password
                <input
                  type="password"
                  minLength={12}
                  value={form.password}
                  onChange={(event) =>
                    onChange({ ...form, password: event.target.value })
                  }
                  required
                />
              </label>
            ) : null}
            {editMode ? (
              <label className="checkbox">
                Akun aktif
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) =>
                    onChange({ ...form, is_active: event.target.checked })
                  }
                />
              </label>
            ) : null}
          </div>
        )}
        <footer>
          <button className="button-secondary" type="button" onClick={onClose}>
            Batal
          </button>
          <button type="submit" disabled={pending}>
            {pending
              ? "Menyimpan…"
              : passwordOnly
                ? "Reset sandi"
                : editMode
                  ? "Simpan perubahan"
                  : "Buat akun"}
          </button>
        </footer>
      </form>
    </div>
  );
}
