import { formatWib } from "@/lib/formatters";

export function FreshnessLabel({ checkedAt, staleAfterMinutes = 5 }: { checkedAt: string | null | undefined; staleAfterMinutes?: number }) {
  if (!checkedAt) return <span className="freshness freshness-unknown" title="Belum ada pemeriksaan">Belum ada data</span>;
  const age = Date.now() - new Date(checkedAt).getTime();
  const isStale = Number.isNaN(age) || age > staleAfterMinutes * 60_000;
  return <span className={isStale ? "freshness freshness-stale" : "freshness freshness-fresh"} title={formatWib(checkedAt)}>{isStale ? "Stale" : "Fresh"}</span>;
}
