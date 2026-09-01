export function MetricCard({ label, value }: { label: string; value: React.ReactNode }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong></article>;
}

export function MetricGrid({ children, columns = 4 }: Readonly<{ children: React.ReactNode; columns?: 3 | 4 | 5 | 6 | 8 }>) {
  return <section className={`metric-grid metric-grid-${columns}`}>{children}</section>;
}
