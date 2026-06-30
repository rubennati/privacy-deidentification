import { SectionHeading } from "./SectionHeading";

interface ComparisonCard {
  title: string;
  example: string;
  result: string;
  emphasis?: "weak" | "strong";
}

const CARDS: ComparisonCard[] = [
  {
    title: "Schwärzung",
    example: "„████ wohnt in ████.“",
    result: "Der Kontext geht verloren. Die Antwort wird ungenau oder unbrauchbar.",
    emphasis: "weak",
  },
  {
    title: "Einfache Maskierung",
    example: "„[REDACTED] wohnt in [REDACTED].“",
    result: "Die Daten sind entfernt, aber die Bedeutung fehlt.",
    emphasis: "weak",
  },
  {
    title: "Semantische De-Identification",
    example: "„[[PERSON-7F3A]] wohnt in [[ADDRESS-19C4]].“",
    result: "Der Kontext bleibt erhalten. Die echten Daten werden nicht offengelegt.",
    emphasis: "strong",
  },
];

/** Three side-by-side cards comparing redaction, masking, and semantic de-identification. */
export function ComparisonSection() {
  return (
    <section>
      <SectionHeading title="Drei Wege im Vergleich" />

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        {CARDS.map((card) => (
          <article
            key={card.title}
            className={[
              "rounded-xl border p-5",
              card.emphasis === "strong"
                ? "border-accent/30 bg-accent-soft"
                : "border-card-border bg-card",
            ].join(" ")}
          >
            <h3 className="text-sm font-semibold text-ink">{card.title}</h3>
            <p className="mt-3 text-xs font-medium uppercase tracking-wide text-muted">
              Was die KI sieht
            </p>
            <p className="mt-1.5 font-mono text-sm text-ink">{card.example}</p>
            <p className="mt-4 text-sm text-muted">{card.result}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
