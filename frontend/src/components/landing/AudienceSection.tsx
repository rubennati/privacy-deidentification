import { SectionHeading } from "./SectionHeading";

const AUDIENCES = [
  "Rechtsberatung",
  "Versicherung",
  "Gesundheitswesen",
  "Finanzdienstleistungen",
  "HR und Recruiting",
  "öffentliche Verwaltung",
  "interne Wissens- und Dokumentenprozesse",
] as const;

/** Who the project is for, plus the list of particularly relevant domains. */
export function AudienceSection() {
  return (
    <section>
      <SectionHeading title="Für wen" />

      <p className="mt-4 text-sm text-muted">
        Privacy De-Identification eignet sich für Teams, die sensible Dokumente mit KI oder
        Automatisierungen nutzen möchten, ohne den Kontrollverlust über Originaldaten zu
        akzeptieren.
      </p>

      <p className="mt-4 text-xs font-medium uppercase tracking-wide text-muted">
        Besonders relevant für
      </p>
      <ul className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {AUDIENCES.map((audience) => (
          <li key={audience} className="flex items-center gap-2 text-sm text-ink">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
            {audience}
          </li>
        ))}
      </ul>
    </section>
  );
}
