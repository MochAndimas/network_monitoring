export function Pagination({ offset, limit, total, onChange }: { offset: number; limit: number; total: number | null; onChange: (offset: number) => void }) {
  const from = total === 0 ? 0 : offset + 1;
  const to = total === null ? offset + limit : Math.min(offset + limit, total);
  const hasNext = total === null || offset + limit < total;
  return <div className="pagination" aria-label="Pagination"><span>Menampilkan {from}–{to}{total !== null ? ` dari ${total}` : ""}</span>
    <div><button className="button-secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Sebelumnya</button>
      <button className="button-secondary" disabled={!hasNext} onClick={() => onChange(offset + limit)}>Berikutnya</button></div>
  </div>;
}
