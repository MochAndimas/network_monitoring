export function MetaStrip({ items }: { items: ReadonlyArray<{ label: string; value: React.ReactNode }> }) {
  return <dl className="meta-strip">
    {items.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
  </dl>;
}
