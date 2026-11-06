import { describe, expect, it } from "vitest";
import {
  barPercent,
  exactBytes,
  formatBytes,
  formatEpochNs,
  rangeError,
  summarizeUsage,
} from "./format";
import type { UsageRow } from "./types";

describe("bandwidth integer accounting", () => {
  it("preserves counters past JavaScript's safe integer and signed BIGINT limits", () => {
    const row = {
      upload_bytes: "9007199254740993",
      download_bytes: "18446744073709551614",
      total_bytes: "18455751272964292607",
      estimated_bytes: "9007199254740993",
      unresolved_bytes: "0",
      updated_ns: "1791997200000000001",
    } as UsageRow;
    const totals = summarizeUsage([row, row]);
    expect(totals.upload).toBe(18014398509481986n);
    expect(totals.total).toBe(36911502545928585214n);
    expect(exactBytes(row.upload_bytes)).toBe("9.007.199.254.740.993 byte");
    expect(formatBytes("0")).toBe("0 B");
    expect(formatBytes("1536")).toBe("1,50 KiB");
    expect(formatBytes("18446744073709551614")).toBe("16,00 EiB");
    expect(barPercent("9007199254740993", "18014398509481986")).toBe(50);
    expect(barPercent("0", "0")).toBe(0);
  });

  it("reduces nanoseconds only for the WIB display timestamp", () => {
    expect(formatEpochNs("1791997200000000001")).toContain("15 Okt 2026");
    expect(formatEpochNs(undefined)).toBe("—");
  });
});

describe("inclusive report range", () => {
  it("allows 31 calendar days and rejects 32, invalid dates, empty and reversed inputs", () => {
    expect(rangeError({ start: "2026-10-01", end: "2026-10-31" })).toBeNull();
    expect(rangeError({ start: "2026-10-01", end: "2026-11-01" })).toContain(
      "31 hari",
    );
    expect(rangeError({ start: "2026-02-30", end: "2026-03-01" })).toContain(
      "valid",
    );
    expect(rangeError({ start: "", end: "2026-03-01" })).toContain("valid");
    expect(rangeError({ start: "2026-10-15", end: "2026-10-14" })).toContain(
      "melewati",
    );
    expect(rangeError({ start: "2028-02-29", end: "2028-02-29" })).toBeNull();
  });
});
