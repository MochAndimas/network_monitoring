"use client";

import { ReactNode } from "react";

export function ConfirmDialog({ title, children, confirmLabel = "Konfirmasi", pending, onConfirm, onClose }: { title: string; children: ReactNode; confirmLabel?: string; pending?: boolean; onConfirm: () => void; onClose: () => void }) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><h2 id="dialog-title">{title}</h2><div>{children}</div><footer><button className="button-secondary" type="button" disabled={pending} onClick={onClose}>Batal</button><button className="button-danger" type="button" disabled={pending} onClick={onConfirm}>{pending ? "Memproses…" : confirmLabel}</button></footer></section></div>;
}
