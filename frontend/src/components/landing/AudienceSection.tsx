import { SectionHeading } from "./SectionHeading";

const AUDIENCES = [
  {
    title: "Juristische Beratung und Compliance",
    description: "Schnelle Durchsicht langer Verträge ohne Preisgabe der Mandatsdaten.",
  },
  {
    title: "Versicherungs- und Schadenbearbeitung",
    description: "Analyse von Schadensmeldungen und Aktenzeichen in großem Umfang.",
  },
  {
    title: "Gesundheitswesen",
    description:
      "Anonymisierung von Entlassberichten und medizinischen Dokumenten bei gleichbleibender Kontexttreue.",
  },
  {
    title: "Finanz- und Steuerwesen",
    description: "Sichere Verarbeitung von Konto-, Kredit- und Steuerdaten.",
  },
  {
    title: "Personalabteilungen und Recruiting",
    description: "Bewertung von Bewerbungen ohne Offenlegung sensibler Daten.",
  },
  {
    title: "Öffentliche Verwaltung und Wissensprozesse",
    description: "Austausch sensibler Bürger- oder Mitarbeiterdaten in Chatbots und Automationen.",
  },
] as const;

/** Who the service is for, with a concrete use case per domain. */
export function AudienceSection() {
  return (
    <section>
      <SectionHeading title="Zielgruppen und Einsatzbereiche" />

      <p className="mt-4 text-sm text-muted">
        Der Dienst richtet sich an Teams, die mit sensiblen Dokumenten arbeiten und KI-Modelle
        oder Automatisierungen nutzen möchten, ohne die Kontrolle über die Rohdaten zu verlieren.
      </p>

      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {AUDIENCES.map((audience) => (
          <li
            key={audience.title}
            className="rounded-lg border border-card-border bg-card p-4"
          >
            <p className="text-sm font-medium text-ink">{audience.title}</p>
            <p className="mt-1 text-sm text-muted">{audience.description}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
