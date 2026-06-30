import { Link } from "react-router-dom";

/** Closing call to action that sends the visitor to the upload page. */
export function FinalCta() {
  return (
    <section className="rounded-2xl border border-card-border bg-card p-8 text-center sm:p-10">
      <h2 className="text-lg font-semibold text-ink sm:text-xl">Mit einem Dokument starten</h2>
      <p className="mt-3 text-sm text-muted">
        Laden Sie ein Dokument hoch und starten Sie den vorbereiteten Workflow.
      </p>
      <Link
        to="/upload"
        className="mt-6 inline-flex items-center justify-center rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-dark"
      >
        Zur Upload-Seite
      </Link>
    </section>
  );
}
