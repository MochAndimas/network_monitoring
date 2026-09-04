import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable } from "./data-table";

const columns = [{ key: "name", label: "Nama", render: (row: { name: string }) => row.name }];

describe("DataTable", () => {
  it("paginates locally and shows the selected page range", () => {
    render(<DataTable columns={columns} rows={[{ name: "A" }, { name: "B" }, { name: "C" }]} pageSize={2} />);
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.queryByText("C")).not.toBeInTheDocument();
    expect(screen.getByText("Menampilkan 1–2 dari 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Berikutnya" }));
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.getByText("Menampilkan 3–3 dari 3")).toBeInTheDocument();
  });

  it("renders the supplied empty label", () => {
    render(<DataTable columns={columns} rows={[]} emptyLabel="Tidak ada hasil" />);
    expect(screen.getByText("Tidak ada hasil")).toBeInTheDocument();
  });

  it("uses 10 rows as the default page size", () => {
    const rows = Array.from({ length: 11 }, (_, index) => ({ name: `Row ${index + 1}` }));
    render(<DataTable columns={columns} rows={rows} />);
    expect(screen.getByText("Row 10")).toBeInTheDocument();
    expect(screen.queryByText("Row 11")).not.toBeInTheDocument();
    expect(screen.getByText("Menampilkan 1–10 dari 11")).toBeInTheDocument();
  });
});
