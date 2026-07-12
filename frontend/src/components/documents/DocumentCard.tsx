import { Link } from "react-router-dom";

import { formatBytes, formatTimestamp } from "../../lib/format";
import type { DocumentAnalysisState } from "../../lib/documentListStatus";

interface DocumentCardProps {
  id: string;
  filename: string;
  size: number;
  uploadedAt: string;
  /** Derived analysis state for the badge; undefined (state unknown) renders no badge. */
  analysis?: DocumentAnalysisState;
  onDelete: (id: string) => void;
  deleting?: boolean;
}

const ANALYSIS_BADGES: Record<DocumentAnalysisState, { label: string; className: string }> = {
  analyzed: { label: "Analysiert", className: "bg-accent-soft text-accent-dark" },
  running: { label: "Analyse läuft …", className: "bg-amber-100 text-amber-800" },
  none: { label: "Nicht analysiert", className: "bg-gray-100 text-gray-600" },
};

/** One row in the documents list: filename, timestamp, size, analysis badge, delete action. */
export function DocumentCard({
  id,
  filename,
  size,
  uploadedAt,
  analysis,
  onDelete,
  deleting = false,
}: DocumentCardProps) {
  const handleDelete = () => {
    if (window.confirm(`„${filename}“ wirklich löschen?`)) {
      onDelete(id);
    }
  };

  const badge = analysis ? ANALYSIS_BADGES[analysis] : null;

  return (
    <li className="flex items-center justify-between gap-4 rounded-xl border border-card-border bg-card p-4 transition-colors hover:border-accent/40">
      <Link
        to={`/documents/${encodeURIComponent(id)}`}
        className="min-w-0 flex-1 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <p className="truncate text-sm font-medium text-ink hover:text-accent-dark">{filename}</p>
        <p className="mt-1 text-xs text-muted">
          {formatTimestamp(uploadedAt)} • {formatBytes(size)}
        </p>
      </Link>

      <div className="flex shrink-0 items-center gap-3">
        {badge && (
          <span
            data-testid="analysis-badge"
            className={`rounded-full px-2.5 py-1 text-xs font-medium ${badge.className}`}
          >
            {badge.label}
          </span>
        )}
        {/* Deliberately quiet: deletion is a rare, destructive action and must not compete with
            the primary "open document" affordance on every row. */}
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleting}
          className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-red-50 hover:text-red-700 focus-visible:ring-2 focus-visible:ring-red-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {deleting ? "Wird gelöscht …" : "Löschen"}
        </button>
      </div>
    </li>
  );
}
