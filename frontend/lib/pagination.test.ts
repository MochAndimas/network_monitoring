import { describe, expect, it } from "vitest";
import { DEFAULT_PAGE_SIZE, initialPageSize, pageRange } from "./pagination";

describe("initialPageSize", () => {
  it("accepts only supported page sizes from URL state", () => {
    expect(initialPageSize("25")).toBe(25);
    expect(initialPageSize("100")).toBe(100);
    expect(DEFAULT_PAGE_SIZE).toBe(10);
    expect(initialPageSize("35")).toBe(DEFAULT_PAGE_SIZE);
    expect(initialPageSize(null)).toBe(DEFAULT_PAGE_SIZE);
    expect(initialPageSize("200", [50, 100, 200, 500], 100)).toBe(200);
    expect(initialPageSize("25", [50, 100, 200, 500], 100)).toBe(100);
  });
});

describe("pageRange", () => {
  it("returns a human-readable server page coverage range", () => {
    expect(pageRange(144, 50, 50)).toEqual({ start: 51, end: 100 });
    expect(pageRange(144, 100, 25)).toEqual({ start: 101, end: 125 });
    expect(pageRange(0, 0, 0)).toEqual({ start: 0, end: 0 });
  });
});
