"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { useDebouncedValue } from "@/lib/use-debounced-value";

function initialOffset(value: string | null) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}
export function useDeviceFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<"inventory" | "manage">(() =>
    searchParams.get("tab") === "manage" ? "manage" : "inventory",
  );
  const [search, setSearch] = useState(() => searchParams.get("q") ?? "");
  const [type, setType] = useState(() => searchParams.get("type") ?? "");
  const [status, setStatus] = useState(() => searchParams.get("status") ?? "");
  const [activeOnly, setActiveOnly] = useState(
    () => searchParams.get("active") === "true",
  );
  const [offset, setOffset] = useState(() =>
    initialOffset(searchParams.get("offset")),
  );
  const debouncedSearch = useDebouncedValue(search);
  const resetPage = () => setOffset(0);
  useEffect(() => {
    const params = new URLSearchParams();
    if (tab !== "inventory") params.set("tab", tab);
    if (search) params.set("q", search);
    if (type) params.set("type", type);
    if (status) params.set("status", status);
    if (activeOnly) params.set("active", "true");
    if (offset) params.set("offset", String(offset));
    const next = params.toString();
    if (next !== searchParams.toString())
      router.replace(next ? `${pathname}?${next}` : pathname, {
        scroll: false,
      });
  }, [
    activeOnly,
    offset,
    pathname,
    router,
    search,
    searchParams,
    status,
    tab,
    type,
  ]);
  return {
    tab,
    setTab,
    search,
    setSearch,
    type,
    setType,
    status,
    setStatus,
    activeOnly,
    setActiveOnly,
    offset,
    setOffset,
    debouncedSearch,
    resetPage,
  };
}
