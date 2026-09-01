export function LoadingState({ label = "Memuat data…" }: { label?: string }) {
  return <p className="page-state" aria-live="polite">{label}</p>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <section className="page-state page-state-error" role="alert">
      <p>{message}</p>
      {onRetry ? <button type="button" onClick={onRetry}>Coba lagi</button> : null}
    </section>
  );
}
