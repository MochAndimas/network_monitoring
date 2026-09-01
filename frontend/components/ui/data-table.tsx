import { ReactNode } from "react";

export type TableColumn<Row> = { key: string; label: string; render: (row: Row) => ReactNode };

export function DataTable<Row>({ columns, rows, emptyLabel = "Tidak ada data untuk filter ini." }: {
  columns: readonly TableColumn<Row>[]; rows: readonly Row[]; emptyLabel?: string;
}) {
  return <div className="table-wrap"><table>
    <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
    <tbody>{rows.length ? rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}</tr>) :
      <tr><td className="table-empty" colSpan={columns.length}>{emptyLabel}</td></tr>}</tbody>
  </table></div>;
}
