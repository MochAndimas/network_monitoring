export function LoadingState({ label = "Memuat data…", inline = false }: { label?: string; inline?: boolean }) {
  return <p className={inline ? "section-caption" : "page-state"} aria-live="polite">{label}</p>;
}

export function ErrorState({ message, onRetry, inline = false, retrying = false }: {
  message: string;
  onRetry?: () => void;
  inline?: boolean;
  retrying?: boolean;
}) {
  return (
    <section className={inline ? "page-state-error" : "page-state page-state-error"} role="alert">
      <p>{message}</p>
      {onRetry ? <button type="button" disabled={retrying} onClick={onRetry}>{retrying ? "Memuat…" : "Coba lagi"}</button> : null}
    </section>
  );
}
