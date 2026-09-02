"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

type QueryValue = string | number | boolean | null | undefined;

/** Keep sharable filter state in the URL without adding browser-history noise per keystroke. */
export function useUrlQuerySync(values: Record<string, QueryValue>) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const serialized = useMemo(() => {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "" && value !== false && value !== 0) params.set(key, String(value));
    });
    return params.toString();
  }, [values]);
  useEffect(() => {
    if (serialized !== searchParams.toString()) router.replace(serialized ? `${pathname}?${serialized}` : pathname, { scroll: false });
  }, [pathname, router, searchParams, serialized]);
}

export function initialOffset(value: string | null) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}
