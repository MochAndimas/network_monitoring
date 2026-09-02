import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CursorPagination } from "./cursor-pagination";

describe("CursorPagination", () => {
  it("uses opaque cursor navigation controls without assuming a total", () => {
    const onNext = vi.fn();
    render(<CursorPagination itemCount={50} limit={50} total={null} pageIndex={1} hasNext hasPrevious onNext={onNext} onPrevious={vi.fn()} />);

    expect(screen.getByText("Menampilkan 51–100")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Berikutnya" }));
    expect(onNext).toHaveBeenCalledOnce();
  });
});
