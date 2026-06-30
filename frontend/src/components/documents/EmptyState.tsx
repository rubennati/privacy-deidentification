import { Link } from "react-router-dom";

/** Shown on the documents page when nothing has been uploaded yet. */
export function EmptyState() {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-dropzone-border bg-dropzone p-10 text-center">
      <p className="text-sm text-muted">Noch keine Dokumente vorhanden.</p>
      <Link
        to="/upload"
        className="mt-4 inline-flex items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-dark"
      >
        Dokument hochladen
      </Link>
    </div>
  );
}
