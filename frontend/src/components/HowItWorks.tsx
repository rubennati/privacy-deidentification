const STEPS = [
  "Dokument hochladen",
  "Inhalte werden extrahiert und analysiert",
  "Sensible Informationen werden geprüft und vorbereitet",
  "Ergebnis für Export, Redaction oder Pseudonymisierung nutzen",
] as const;

/** The "So läuft es ab" process overview and the privacy-first footer badge. */
export function HowItWorks() {
  return (
    <section className="mt-8">
      <h2 className="text-sm font-medium text-ink">So läuft es ab</h2>

      <ol className="mt-4 grid gap-3 sm:grid-cols-2">
        {STEPS.map((step, index) => (
          <li
            key={step}
            className="flex items-start gap-3 rounded-lg border border-card-border bg-dropzone p-3"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
              {index + 1}
            </span>
            <span className="text-sm text-muted">{step}</span>
          </li>
        ))}
      </ol>

      <div className="mt-8 flex justify-center">
        <span className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent-dark">
          <ShieldIcon />
          Privacy-first • Kontrollierte Verarbeitung • Review vor Export
        </span>
      </div>
    </section>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}
