import { describe, expect, it } from "vitest";
import { toWibDate, toWibOffsetTimestamp } from "./wib-time";

describe("toWibOffsetTimestamp", () => {
  it("keeps an absolute timestamp in the server's WIB filter timezone", () => {
    expect(toWibOffsetTimestamp(new Date("2026-09-02T07:45:23Z"))).toBe("2026-09-02T14:45:23+07:00");
  });

  it("formats a calendar date in WIB", () => {
    expect(toWibDate(new Date("2026-09-02T18:00:00Z"))).toBe("2026-09-03");
  });
});
