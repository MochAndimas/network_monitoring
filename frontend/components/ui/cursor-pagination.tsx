type CursorPaginationProps = {
  itemCount: number;
  limit: number;
  total: number | null;
  pageIndex: number;
  hasNext: boolean;
  hasPrevious: boolean;
  onNext: () => void;
  onPrevious: () => void;
};

/** Pagination controls for APIs that expose opaque forward cursors instead of offsets. */
export function CursorPagination({ itemCount, limit, total, pageIndex, hasNext, hasPrevious, onNext, onPrevious }: CursorPaginationProps) {
  const start = itemCount === 0 ? 0 : pageIndex * limit + 1;
  const end = itemCount === 0 ? 0 : start + itemCount - 1;
  const coverage = total === null ? `${start}–${end}` : `${start}–${Math.min(end, total)} dari ${total}`;

  return <div className="pagination" aria-label="Pagination riwayat"><span>Menampilkan {coverage}</span>
    <div><button className="button-secondary" disabled={!hasPrevious} onClick={onPrevious}>Sebelumnya</button>
      <button className="button-secondary" disabled={!hasNext} onClick={onNext}>Berikutnya</button></div>
  </div>;
}
