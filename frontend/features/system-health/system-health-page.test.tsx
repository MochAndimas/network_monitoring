import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useQuery } from "@tanstack/react-query";
import { SystemHealthPage } from "./system-health-page";
vi.mock("@tanstack/react-query", () => ({ useQuery: vi.fn() }));
it("shows an error when one request fails while the other is still pending", () => {
  vi.mocked(useQuery).mockReturnValueOnce({ isError: true, isPending: false } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ isError: false, isPending: true } as ReturnType<typeof useQuery>);
  render(<SystemHealthPage />);
  expect(screen.getByRole("alert")).toHaveTextContent("30 detik");
  expect(screen.queryByText("Memuat data…")).not.toBeInTheDocument();
});
