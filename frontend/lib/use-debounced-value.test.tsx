import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./use-debounced-value";

afterEach(() => vi.useRealTimers());

describe("useDebouncedValue", () => {
  it("holds transient input until the configured delay has elapsed", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), { initialProps: { value: "router" } });
    rerender({ value: "router-core" });
    expect(result.current).toBe("router");
    act(() => vi.advanceTimersByTime(299));
    expect(result.current).toBe("router");
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe("router-core");
  });
});
