import { SectionHeading } from "./SectionHeading";

const FORMATS = [
  {
    title: "PDF und Scans",
    description: "Native oder gescannte PDFs werden mittels OCR in durchsuchbare Textform gebracht.",
  },
  {
    title: "Office-Dateien",
    description: "Word- und Excel-Dokumente werden inklusive Tabellen analysiert.",
  },
  {
    title: "Bilder",
    description: "Unterstützt werden gängige Bildformate wie PNG, JPG oder TIFF.",
  },
  {
    title: "Text- und Strukturdaten",
    description: "Reine Textdateien sowie CSV und JSON können direkt verarbeitet werden.",
  },
] as const;

/** Planned input formats and how each is handled. */
export function FormatsSection() {
  return (
    <section>
      <SectionHeading title="Formate und Verarbeitung" />
      <p className="mt-3 text-sm text-muted">Geplant sind Workflows für:</p>

      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {FORMATS.map((format) => (
          <li key={format.title} className="rounded-lg border border-card-border bg-card p-4">
            <p className="text-sm font-medium text-ink">{format.title}</p>
            <p className="mt-1 text-sm text-muted">{format.description}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
