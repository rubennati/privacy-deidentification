import { SectionHeading } from "./SectionHeading";

const FAILING_APPROACHES = [
  {
    label: "Schwärzung",
    example: "„███ wohnt in ███.“",
    problem: "Es bleiben nur schwarze Balken — der semantische Zusammenhang bricht.",
  },
  {
    label: "Generische Maskierung",
    example: "„[REDACTED] wohnt in [REDACTED].“",
    problem: "Die Werte sind entfernt, aber die Bedeutung fehlt weiterhin.",
  },
] as const;

/**
 * Explains the context-preserving pseudonymization approach and why plain redaction or
 * generic masking destroys the meaning a model needs.
 */
export function RedactionContextSection() {
  return (
    <section id="kontextbewahrende-pseudonymisierung" className="scroll-mt-8">
      <SectionHeading title="Kontextbewahrende Pseudonymisierung" />

      <p className="mt-4 text-sm text-muted">
        Unser Ansatz unterscheidet sich von herkömmlicher Schwärzung: Statt Textstellen zu
        übermalen, ersetzen wir sie durch beschreibende Platzhalter wie „Arztdaten-123" oder
        „Vertrags-ID-92B1". So bleibt für das Modell ersichtlich, dass eine Person, eine
        Bankverbindung oder ein Firmenname gemeint ist — und Sie behalten die Möglichkeit, das
        Original später gezielt wieder einzusetzen.
      </p>

      <div className="mt-6 rounded-xl border border-card-border bg-card p-5 sm:p-6">
        <p className="text-sm font-medium text-ink">Warum einfache Schwärzung nicht reicht</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {FAILING_APPROACHES.map((approach) => (
            <div key={approach.label}>
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                {approach.label}
              </p>
              <p className="mt-1.5 font-mono text-sm text-ink">{approach.example}</p>
              <p className="mt-2 text-sm text-muted">{approach.problem}</p>
            </div>
          ))}
        </div>
        <p className="mt-5 border-t border-card-border pt-4 text-sm text-muted">
          Nur kontext-typisierte Platzhalter erhalten die Bedeutung der entfernten Daten:
          <span className="mt-1.5 block font-mono text-accent-dark">
            „[[Person-X1]] wohnt in [[Adresse-19C4]].“
          </span>
        </p>
      </div>
    </section>
  );
}
