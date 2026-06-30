import { SectionHeading } from "./SectionHeading";

const STEPS = [
  {
    title: "Upload",
    description:
      "Laden Sie PDFs, Office-Dateien, Bilder oder strukturierte Formate in eine geschützte Umgebung.",
  },
  {
    title: "Extraktion",
    description: "Texte, Tabellen und relevante Inhalte werden per OCR oder Parser erfasst.",
  },
  {
    title: "Erkennung sensibler Informationen",
    description:
      "Personenbezogene und geschäftliche Kennzahlen werden mit geprüften Erkennungsmodellen identifiziert.",
  },
  {
    title: "Überprüfung",
    description:
      "Vor der Weitergabe können Sie die gefundenen Stellen einsehen, anpassen oder ignorieren.",
  },
  {
    title: "Pseudonymisierte Version",
    description:
      "Wir erzeugen ein Dokument mit Platzhaltern. Optional speichern Sie ein Mapping, um die Daten später gezielt zurückzuführen.",
  },
] as const;

/** The five-step processing workflow, rendered as a compact responsive card grid. */
export function WorkflowSection() {
  return (
    <section>
      <SectionHeading title="Ablauf im Überblick" />

      <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map((step, index) => (
          <li key={step.title} className="rounded-xl border border-card-border bg-card p-4">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-dark">
              {index + 1}
            </span>
            <h3 className="mt-3 text-sm font-semibold text-ink">{step.title}</h3>
            <p className="mt-1.5 text-sm text-muted">{step.description}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
