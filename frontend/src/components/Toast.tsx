interface ToastProps {
  message: string;
  /** Optional single action (e.g. "Rückgängig"); rendered as a text button beside the message. */
  actionLabel?: string;
  onAction?: () => void;
  onClose: () => void;
}

/**
 * One quiet confirmation at the bottom of the viewport. The caller owns lifetime (auto-dismiss
 * timer) and stacking; this stays a single toast by design — the page never queues several.
 */
export function Toast({ message, actionLabel, onAction, onClose }: ToastProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="toast"
      className="fixed bottom-5 left-1/2 z-40 flex -translate-x-1/2 items-center gap-4 rounded-xl border border-card-border bg-ink px-4 py-2.5 text-sm text-white shadow-[0_8px_30px_rgba(17,24,39,0.25)]"
    >
      <span>{message}</span>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="rounded font-semibold text-emerald-300 hover:text-emerald-200 focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:outline-none"
        >
          {actionLabel}
        </button>
      )}
      <button
        type="button"
        onClick={onClose}
        aria-label="Hinweis schließen"
        className="rounded px-1 text-lg leading-none text-white/60 hover:text-white focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:outline-none"
      >
        ×
      </button>
    </div>
  );
}
