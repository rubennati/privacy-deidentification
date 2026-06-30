import { Link } from "react-router-dom";

/** Page title, lead paragraphs, and the two calls to action. */
export function Hero() {
  return (
    <header className="mx-auto max-w-3xl text-center">
      <h1 className="text-2xl font-semibold leading-tight text-ink sm:text-3xl">
        Dokumente für KI vorbereiten, ohne sensible Daten offenzulegen
      </h1>

      <p className="mt-5 text-base text-muted">
        Nutzen Sie moderne KI-Modelle mit realen Dokumenten, ohne personenbezogene oder
        geschäftskritische Informationen unnötig weiterzugeben.
      </p>

      <p className="mt-4 text-base text-muted">
        Privacy De-Identification bereitet Dokumente vor, bevor sie in KI-Systemen, Workflows
        oder externen Tools weiterverarbeitet werden. Sensible Inhalte werden erkannt, geprüft
        und durch semantische Platzhalter ersetzt. So bleibt der fachliche Kontext erhalten,
        während echte Daten geschützt bleiben.
      </p>

      <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          to="/upload"
          className="inline-flex items-center justify-center rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-dark"
        >
          Dokument hochladen
        </Link>
        <a
          href="#warum-schwaerzung-nicht-reicht"
          className="inline-flex items-center justify-center rounded-lg px-5 py-2.5 text-sm font-medium text-accent-dark transition-colors hover:bg-accent-soft"
        >
          Mehr erfahren
        </a>
      </div>
    </header>
  );
}
