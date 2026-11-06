"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { DailyUsageReport } from "./daily-usage-report";
import type { ReportRange } from "./types";

export function ClientUsageDialog({
  routerId,
  range,
  clientId,
  name,
  onClose,
}: {
  routerId: number;
  range: ReportRange;
  clientId: number;
  name: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus({ preventScroll: true });
    };
  }, []);

  if (typeof document === "undefined") return null;
  return createPortal(
    <dialog
      ref={dialog}
      className="bandwidth-detail-dialog"
      aria-labelledby="bandwidth-detail-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="bandwidth-dialog-content">
        <header className="section-header">
          <h2 id="bandwidth-detail-title">Detail bandwidth · {name}</h2>
          <button type="button" className="button-secondary" onClick={onClose}>
            Tutup detail
          </button>
        </header>
        <p className="bandwidth-help">
          Periode {range.start} s.d. {range.end} (WIB). Penggunaan tercatat
          berdasarkan identitas perangkat yang terverifikasi.
        </p>
        <DailyUsageReport
          routerId={routerId}
          range={range}
          clientId={clientId}
          name={name}
        />
        <p className="bandwidth-help">
          Kelengkapan traffic belum terverifikasi. Flow lintas hari dialokasikan
          secara estimasi.
        </p>
      </div>
    </dialog>,
    document.body,
  );
}
