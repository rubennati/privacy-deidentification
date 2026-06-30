import { formatBytes, formatTimestamp } from "../../lib/format";

interface DocumentCardProps {
  id: string;
  filename: string;
  size: number;
  uploadedAt: string;
  onDelete: (id: string) => void;
  deleting?: boolean;
}

/** One row in the documents list: filename, timestamp, size, status badge, delete action. */
export function DocumentCard({
  id,
  filename,
  size,
  uploadedAt,
  onDelete,
  deleting = false,
}: DocumentCardProps) {
  const handleDelete = () => {
    if (window.confirm(`„${filename}“ wirklich löschen?`)) {
      onDelete(id);
    }
  };

  return (
    <li className="flex items-center justify-between gap-4 rounded-xl border border-card-border bg-card p-4">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">{filename}</p>
        <p className="mt-1 text-xs text-muted">
          {formatTimestamp(uploadedAt)} • {formatBytes(size)}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <span className="rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent-dark">
          Entgegengenommen
        </span>
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleting}
          className="rounded-lg px-3 py-1.5 text-xs font-medium text-red-700 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {deleting ? "Wird gelöscht …" : "Löschen"}
        </button>
      </div>
    </li>
  );
}
