import { Link } from "react-router-dom";

/** Page title, lead paragraph, and the two calls to action. */
export function Hero() {
  return (
    <header className="mx-auto max-w-3xl text-center">
      <h1 className="text-2xl font-semibold leading-tight text-ink sm:text-3xl">
        Sensible Dokumente sicher für KI-Analysen vorbereiten
      </h1>

      <p className="mt-5 text-base text-muted">
        Nutzen Sie moderne KI-Modelle, ohne vertrauliche Informationen preiszugeben. Persönliche
        und geschäftskritische Details werden isoliert, bevor sie ein externes System erreichen.
        So bleiben Inhalte verwertbar, während die Privatsphäre gewahrt bleibt.
      </p>

      <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          to="/upload"
          className="inline-flex items-center justify-center rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-dark"
        >
          Dokument hochladen
        </Link>
        <a
          href="#kontextbewahrende-pseudonymisierung"
          className="inline-flex items-center justify-center rounded-lg px-5 py-2.5 text-sm font-medium text-accent-dark transition-colors hover:bg-accent-soft"
        >
          Mehr erfahren
        </a>
      </div>
    </header>
  );
}
