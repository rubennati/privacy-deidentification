import { SectionHeading } from "./SectionHeading";

const STEPS = [
  {
    title: "Dokument hochladen",
    description:
      "PDFs, Office-Dokumente, Bilder oder strukturierte Dateien werden in eine kontrollierte Verarbeitungsumgebung geladen.",
  },
  {
    title: "Inhalte extrahieren",
    description:
      "Text, Tabellen und relevante Dokumentbereiche werden mit vorhandenen OCR- und Extraction-Werkzeugen vorbereitet.",
  },
  {
    title: "Sensible Informationen erkennen",
    description:
      "Personenbezogene und geschäftskritische Informationen werden durch bewährte Erkennungs-Engines und ergänzende Regeln identifiziert.",
  },
  {
    title: "Review durchführen",
    description:
      "Vor der Weiterverarbeitung sieht der Nutzer, welche Inhalte erkannt wurden. Treffer können bestätigt, angepasst oder verworfen werden.",
  },
  {
    title: "De-identifizierte Ausgabe erzeugen",
    description:
      "Das Dokument oder der Text wird mit semantischen Platzhaltern vorbereitet. Optional kann ein lokales Mapping erzeugt werden, um Platzhalter später kontrolliert zurückzuführen.",
  },
] as const;

/** The five-step processing workflow, rendered as a compact responsive card grid. */
export function WorkflowSection() {
  return (
    <section>
      <SectionHeading title="Der Workflow" />

      <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map((step, index) => (
          <li
            key={step.title}
            className="rounded-xl border border-card-border bg-card p-4"
          >
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
