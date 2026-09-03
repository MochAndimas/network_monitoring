export const PAGE_SIZES = [25, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 25;

export function initialPageSize(value: string | null, pageSizes: readonly number[] = PAGE_SIZES, defaultPageSize = DEFAULT_PAGE_SIZE) {
  const pageSize = Number(value);
  return pageSizes.includes(pageSize) ? pageSize : defaultPageSize;
}

export function pageRange(total: number, offset: number, itemCount: number) {
  if (total === 0) return { start: 0, end: 0 };
  return { start: offset + 1, end: Math.min(offset + itemCount, total) };
}
