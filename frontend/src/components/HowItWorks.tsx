const STEPS = [
  "Laden Sie eine Datei mit Textinhalt hoch",
  "Unser KI-gestütztes System extrahiert alle sensiblen Daten",
  "Alle sensiblen Informationen werden mit Codes ersetzt",
  "Sie erhalten den anonymisierten Text",
] as const;

/** The "So einfach ist es!" explainer and the DSGVO footer from Screenshot 1. */
export function HowItWorks() {
  return (
    <section className="mt-8">
      <h2 className="text-sm font-medium text-gray-400">So einfach ist es!</h2>

      <ol className="mt-4 space-y-3">
        {STEPS.map((step, index) => (
          <li key={step} className="flex items-center gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white">
              {index + 1}
            </span>
            <span className="text-sm text-gray-600">{step}</span>
          </li>
        ))}
      </ol>

      <p className="mt-8 flex items-center justify-center gap-2 text-sm text-gray-400">
        <ShieldIcon />
        DSGVO-konform • Maximale Sicherheit
      </p>
    </section>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="16"
      height="16"
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
