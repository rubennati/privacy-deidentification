import { SectionHeading } from "./SectionHeading";

const STAGES = [
  {
    title: "Original",
    text: "Dr. Maria Schmidt bittet um Stellungnahme zu Vertrag Nr. DE2024-7789 mit der Müller GmbH. Die IBAN lautet DE89 3704 0044 0532 0130 00.",
    mono: false,
  },
  {
    title: "Vorbereitete Version",
    text: "[[PERSON-7F3A]] bittet um Stellungnahme zu Vertrag [[CONTRACT-ID-92B1]] mit [[ORGANIZATION-A81C]]. Die IBAN lautet [[IBAN-5D20]].",
    mono: true,
  },
  {
    title: "KI-Antwort",
    text: "[[PERSON-7F3A]] sollte insbesondere die Haftungsregelung in Vertrag [[CONTRACT-ID-92B1]] prüfen. Die Beziehung zur [[ORGANIZATION-A81C]] ist für die Bewertung relevant.",
    mono: true,
  },
  {
    title: "Rekonstruierte Ausgabe",
    text: "Dr. Maria Schmidt sollte insbesondere die Haftungsregelung in Vertrag Nr. DE2024-7789 prüfen. Die Beziehung zur Müller GmbH ist für die Bewertung relevant.",
    mono: false,
  },
] as const;

/** End-to-end example walking a document through all four processing stages. */
export function ExampleSection() {
  return (
    <section>
      <SectionHeading title="Beispiel" />

      <ol className="mt-6 grid gap-4 sm:grid-cols-2">
        {STAGES.map((stage, index) => (
          <li key={stage.title} className="rounded-xl border border-card-border bg-card p-5">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-dark">
                {index + 1}
              </span>
              <h3 className="text-sm font-semibold text-ink">{stage.title}</h3>
            </div>
            <p
              className={[
                "mt-3 text-sm",
                stage.mono ? "font-mono text-accent-dark" : "text-muted",
              ].join(" ")}
            >
              {stage.text}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
