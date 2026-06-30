import { SectionHeading } from "./SectionHeading";

/** Explains why plain redaction loses context, illustrated with one before/after pair. */
export function RedactionContextSection() {
  return (
    <section id="warum-schwaerzung-nicht-reicht" className="scroll-mt-8">
      <SectionHeading title="Warum klassische Schwärzung nicht reicht" />

      <p className="mt-4 text-sm text-muted">
        Wenn sensible Informationen einfach entfernt werden, verliert ein Dokument oft seinen
        Zusammenhang. Aus Namen, Adressen, Aktenzeichen oder Vertragsnummern wird nur noch
        „geschwärzt“. Für eine KI bleibt dann zu wenig Kontext übrig, um präzise zu antworten.
      </p>
      <p className="mt-3 text-sm text-muted">
        Privacy De-Identification verfolgt einen anderen Ansatz: sensible Inhalte werden nicht
        nur entfernt, sondern durch typisierte Platzhalter ersetzt.
      </p>

      <div className="mt-6 rounded-xl border border-card-border bg-card p-5 sm:p-6">
        <dl className="grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted">Original</dt>
            <dd className="mt-1.5 text-sm text-ink">
              Dr. Maria Schmidt bittet um Prüfung des Vertrags Nr. DE2024-7789 mit der Müller
              GmbH.
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted">
              Vorbereitete Version
            </dt>
            <dd className="mt-1.5 font-mono text-sm text-accent-dark">
              [[PERSON-7F3A]] bittet um Prüfung des Vertrags [[CONTRACT-ID-92B1]] mit
              [[ORGANIZATION-A81C]].
            </dd>
          </div>
        </dl>
        <p className="mt-4 border-t border-card-border pt-4 text-sm text-muted">
          Die KI erkennt weiterhin, dass es um eine Person, einen Vertrag und eine Organisation
          geht. Die echten Werte bleiben geschützt.
        </p>
      </div>
    </section>
  );
}
