"use client";

import { ReactNode, useEffect, useState } from "react";

export type TableColumn<Row> = { key: string; label: string; render: (row: Row) => ReactNode };

export function DataTable<Row>({ columns, rows, emptyLabel = "Tidak ada data untuk filter ini.", pageSize = 10 }: {
  columns: readonly TableColumn<Row>[]; rows: readonly Row[]; emptyLabel?: string; pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  useEffect(() => setPage((current) => Math.min(current, totalPages - 1)), [totalPages]);
  const visibleRows = rows.slice(page * pageSize, (page + 1) * pageSize);
  return <><div className="table-wrap"><table>
    <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
    <tbody>{visibleRows.length ? visibleRows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}</tr>) :
      <tr><td className="table-empty" colSpan={columns.length}>{emptyLabel}</td></tr>}</tbody>
  </table></div>{rows.length > pageSize ? <div className="pagination"><span>Menampilkan {page * pageSize + 1}–{Math.min((page + 1) * pageSize, rows.length)} dari {rows.length}</span><div><button className="button-secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Sebelumnya</button><button className="button-secondary" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>Berikutnya</button></div></div> : null}</>;
}
