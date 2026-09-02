export const PAGE_SIZES = [25, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 50;

export function initialPageSize(value: string | null) {
  const pageSize = Number(value);
  return PAGE_SIZES.includes(pageSize as (typeof PAGE_SIZES)[number]) ? pageSize : DEFAULT_PAGE_SIZE;
}

export function pageRange(total: number, offset: number, itemCount: number) {
  if (total === 0) return { start: 0, end: 0 };
  return { start: offset + 1, end: Math.min(offset + itemCount, total) };
}
