import { SectionHeading } from "./SectionHeading";

const STAGES = [
  {
    title: "Original",
    text: "Frau Dr. Schmidt bittet um eine Stellungnahme zum Vertrag NR. AB-12345 mit der Example AG. Die IBAN lautet DE01 2345 6789 0123 4567 89.",
    mono: false,
  },
  {
    title: "Pseudonymisiert",
    text: "[[Person-X1]] bittet um Stellungnahme zu Vertrag [[Vertrags-ID-Z9]] mit [[Unternehmen-Y7]]. Die IBAN lautet [[IBAN-Q5]].",
    mono: true,
  },
  {
    title: "KI-Antwort",
    text: "[[Person-X1]] sollte insbesondere auf die Haftungsregelungen in Vertrag [[Vertrags-ID-Z9]] achten. Die Beziehung zu [[Unternehmen-Y7]] wirkt sich auf die Bewertung aus.",
    mono: true,
  },
  {
    title: "Rekonstruiert",
    text: "Frau Dr. Schmidt sollte insbesondere auf die Haftungsregelungen in Vertrag NR. AB-12345 achten. Die Beziehung zur Example AG ist für die Bewertung relevant.",
    mono: false,
  },
] as const;

/** End-to-end example walking a document through all four stages. */
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
