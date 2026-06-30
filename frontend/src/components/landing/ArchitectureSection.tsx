import { SectionHeading } from "./SectionHeading";

const COMPONENTS = [
  {
    title: "OCR und Extraktion",
    description:
      "Bewährte Open-Source-Werkzeuge wie OCRmyPDF, Tesseract oder MinerU sorgen für zuverlässige Texterkennung.",
  },
  {
    title: "Erkennung und Pseudonymisierung",
    description:
      "Frameworks wie Microsoft Presidio oder noirdoc erkennen PII/PHI mit anpassbaren Regeln und Sprachmodellen und ersetzen sie durch typisierte Platzhalter.",
  },
  {
    title: "Review und Redaktion",
    description:
      "Eine Review-Oberfläche ermöglicht es, erkannte Stellen zu überprüfen und freizugeben.",
  },
  {
    title: "Export",
    description:
      "Für PDFs setzen wir auf PyMuPDF zur echten Redaktion, bei der Text dauerhaft entfernt und nicht nur grafisch geschwärzt wird.",
  },
] as const;

/**
 * Tool-first architecture: proven open-source components integrated via adapters; our own
 * work is orchestration, review UI, file handling, export and secure integration.
 */
export function ArchitectureSection() {
  return (
    <section>
      <SectionHeading title="Architektur und Technologie" />

      <p className="mt-4 text-sm text-muted">
        Wir setzen auf einen modularen Tool-first-Ansatz: bewährte Open-Source-Komponenten
        werden über Adapter eingebunden, statt eigene Erkennungs- oder OCR-Intelligenz zu bauen.
        Die Eigenentwicklung dient der Orchestrierung, der Review-Oberfläche, der
        Dateiverarbeitung, der Exportlogik und der sicheren Integration.
      </p>

      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {COMPONENTS.map((component) => (
          <li
            key={component.title}
            className="rounded-lg border border-card-border bg-card p-4"
          >
            <p className="text-sm font-medium text-ink">{component.title}</p>
            <p className="mt-1 text-sm text-muted">{component.description}</p>
          </li>
        ))}
      </ul>

      <p className="mt-5 text-sm text-muted">
        Diese Komponenten werden in einer geschlossenen Umgebung orchestriert, sodass keine
        externen Server Zugriff auf Ihre Originaldaten erhalten.
      </p>
    </section>
  );
}
