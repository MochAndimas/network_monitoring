"use client";

function csvCell(value: unknown) {
  const raw = String(value ?? "");
  return /[",\n]/.test(raw) ? `"${raw.replaceAll('"', '""')}"` : raw;
}

export function CsvExport({ filename, columns, rows }: { filename: string; columns: readonly string[]; rows: ReadonlyArray<ReadonlyArray<unknown>> }) {
  function download() {
    const content = [columns, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob(["\ufeff", content], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
  }
  return <button type="button" className="button-secondary" onClick={download}>Download CSV</button>;
}
