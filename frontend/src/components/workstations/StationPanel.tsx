import type { ReactNode } from "react";

export type StationStatus = "missing" | "current" | "stale";

interface StationError {
  message: string;
  correlationId: string | null;
}

interface StationPanelProps {
  title: string;
  status: StationStatus;
  actionLabel: string;
  pendingLabel: string;
  pending: boolean;
  disabled: boolean;
  disabledReason?: string;
  actionHint?: string;
  /** Proactive hint when this station's runtime is not installed on this server. Shown
   * regardless of the disabled/pending state so it's visible before a doomed run is attempted. */
  runtimeNotice?: string | null;
  error: StationError | null;
  onAction: () => void;
  children: ReactNode;
}

const STATUS_LABELS: Record<StationStatus, string> = {
  missing: "Noch nicht erstellt",
  current: "Aktuell",
  stale: "Veraltet",
};

const STATUS_STYLES: Record<StationStatus, string> = {
  missing: "bg-gray-100 text-gray-700",
  current: "bg-accent-soft text-accent-dark",
  stale: "bg-amber-100 text-amber-800",
};

export function StationPanel({
  title,
  status,
  actionLabel,
  pendingLabel,
  pending,
  disabled,
  disabledReason,
  actionHint,
  runtimeNotice,
  error,
  onAction,
  children,
}: StationPanelProps) {
  return (
    <section className="flex min-h-52 flex-col rounded-xl border border-card-border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-semibold text-ink">{title}</h2>
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_STYLES[status]}`}>
          {STATUS_LABELS[status]}
        </span>
      </div>
      <div className="mt-4 flex-1 text-sm text-muted">{children}</div>
      {runtimeNotice && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {runtimeNotice}
        </p>
      )}
      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          <p>{error.message}</p>
          {error.correlationId && <p className="mt-1 opacity-70">Referenz: {error.correlationId}</p>}
        </div>
      )}
      <button
        type="button"
        onClick={onAction}
        disabled={disabled}
        aria-busy={pending}
        className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-50"
      >
        {pending ? pendingLabel : actionLabel}
      </button>
      {!pending &&
        (disabled && disabledReason ? (
          <p className="mt-2 text-xs text-muted">{disabledReason}</p>
        ) : actionHint ? (
          <p className="mt-2 text-xs text-muted">{actionHint}</p>
        ) : null)}
    </section>
  );
}
