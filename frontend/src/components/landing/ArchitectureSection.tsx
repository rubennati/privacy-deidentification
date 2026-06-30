import { SectionHeading } from "./SectionHeading";

/** Explains the tool-first architecture principle behind the project. */
export function ArchitectureSection() {
  return (
    <section>
      <SectionHeading title="Architekturprinzip" />

      <div className="mt-4 rounded-xl border border-card-border bg-card p-5 sm:p-6">
        <p className="text-sm text-muted">
          Die Lösung ist tool-first aufgebaut. OCR, De-Identification, Erkennung und Redaction
          werden durch bewährte Open-Source-Komponenten eingebunden. Eigene Entwicklung dient
          der Orchestrierung, Review-Oberfläche, Dateiverarbeitung, Exportlogik und sicheren
          Integration.
        </p>
        <p className="mt-3 text-sm text-muted">
          Ziel ist kein blindes Automatisieren, sondern ein kontrollierter Workflow: erkennen,
          prüfen, freigeben, exportieren.
        </p>
      </div>
    </section>
  );
}
