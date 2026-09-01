"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "@/lib/api/client";

function shouldRetryReadQuery(failureCount: number, error: unknown) {
  if (failureCount >= 2) return false;
  if (error instanceof ApiError) return error.status >= 500 || error.status === 429;
  return !(error instanceof DOMException && error.name === "AbortError");
}

export function QueryProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: shouldRetryReadQuery,
            retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
            refetchOnWindowFocus: false,
            staleTime: 10_000
          }
        }
      })
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
