export type UploadStatus = "idle" | "uploading" | "success" | "warning" | "error";

interface StatusNoticeProps {
  status: UploadStatus;
  message: string;
  correlationId?: string | null;
}

const STYLES: Record<Exclude<UploadStatus, "idle">, string> = {
  uploading: "bg-gray-50 text-gray-700 border-gray-200",
  success: "bg-accent-soft text-accent-dark border-accent/20",
  // For "something needs your attention, but nothing is broken" — visibly calmer than an error.
  warning: "bg-amber-50 text-amber-800 border-amber-200",
  error: "bg-red-50 text-red-800 border-red-200",
};

/** Inline feedback for the upload (uploading / success / error). Hidden while idle. */
export function StatusNotice({ status, message, correlationId }: StatusNoticeProps) {
  if (status === "idle") {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={`mt-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${STYLES[status]}`}
    >
      <Indicator status={status} />
      <span>
        {message}
        {status === "error" && correlationId && (
          <span className="mt-1 block text-xs opacity-70">Referenz: {correlationId}</span>
        )}
      </span>
    </div>
  );
}

function Indicator({ status }: { status: Exclude<UploadStatus, "idle"> }) {
  if (status === "uploading") {
    return (
      <svg
        className="h-4 w-4 shrink-0 animate-spin"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
        <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      </svg>
    );
  }

  // Warning and error share the alert glyph; the container color carries the severity.
  const path =
    status === "success" ? "m9 12 2 2 4-4" : "M12 8v4m0 4h.01";
  return (
    <svg
      className="h-4 w-4 shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d={path} />
    </svg>
  );
}
