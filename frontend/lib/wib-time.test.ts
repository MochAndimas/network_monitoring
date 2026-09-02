import { describe, expect, it } from "vitest";
import { toWibOffsetTimestamp } from "./wib-time";

describe("toWibOffsetTimestamp", () => {
  it("keeps an absolute timestamp in the server's WIB filter timezone", () => {
    expect(toWibOffsetTimestamp(new Date("2026-09-02T07:45:23Z"))).toBe("2026-09-02T14:45:23+07:00");
  });
});
