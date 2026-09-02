import { describe, expect, it } from "vitest";
import { formatWib, statusLabel } from "./formatters";

describe("formatWib", () => {
  it("formats valid timestamps in WIB and handles absent or invalid values", () => {
    expect(formatWib("2026-01-01T00:00:00Z")).toMatch(/07\.00\.00/);
    expect(formatWib(null)).toBe("-");
    expect(formatWib("not-a-date")).toBe("-");
  });
});

describe("statusLabel", () => {
  it("uses standard labels and humanizes unknown values", () => {
    expect(statusLabel("ok")).toBe("OK");
    expect(statusLabel("packet_loss_high")).toBe("Packet Loss High");
    expect(statusLabel(undefined)).toBe("Unknown");
  });
});
