import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it("renders an accessible textual state with its severity class", () => {
    render(<StatusBadge value="critical" />);
    expect(screen.getByText("critical")).toHaveClass("status-danger");
  });

  it("keeps unknown values visible rather than relying on color", () => {
    render(<StatusBadge value="needs_review" />);
    expect(screen.getByText("needs review")).toHaveClass("status-muted");
  });
});
