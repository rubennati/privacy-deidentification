import type { PiiEntity } from "../../api/workstations";
import { entityFeedbackKey, type PiiFeedbackStatus } from "../../api/piiFeedback";
import { PiiEntityCard } from "./PiiEntityCard";

interface PiiEntityListProps {
  entities: readonly PiiEntity[];
  stale: boolean;
  documentId: string;
  /** Id of the PII artifact these entities belong to; used to attach feedback. */
  artifactId: string;
  /** Dev gate: when false, per-entity feedback controls are hidden. */
  feedbackEnabled: boolean;
  /** Latest recorded feedback per entity key (see entityFeedbackKey); empty when none/loading. */
  feedbackStatuses: Record<string, PiiFeedbackStatus>;
}

// A small, non-exhaustive glossary; unknown types fall through to a generic note in the UI.
const ENTITY_TYPE_LEGEND: ReadonlyArray<{ type: string; description: string }> = [
  { type: "PERSON", description: "Personennamen" },
  { type: "ORGANIZATION", description: "Firmen, Vereine, Organisationen" },
  { type: "LOCATION", description: "Orte, Städte, Länder oder Regionen" },
  { type: "ADDRESS", description: "Adressen: Straße mit Hausnummer oder Adresszeilen" },
  { type: "CONTACT_LINE", description: "Kontaktzeile (Name/Telefon/E-Mail einer Person)" },
  { type: "EMAIL_ADDRESS", description: "E-Mail-Adressen" },
  { type: "PHONE_NUMBER", description: "Telefonnummern" },
  { type: "IBAN_CODE", description: "IBAN (Kontonummer)" },
  { type: "URL", description: "Webadressen" },
];

export function PiiEntityList({
  entities,
  stale,
  documentId,
  artifactId,
  feedbackEnabled,
  feedbackStatuses,
}: PiiEntityListProps) {
  return (
    <section aria-labelledby="entity-list-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="entity-list-heading" className="font-semibold text-ink">
          Erkannte Entities
        </h2>
        <span className="text-xs text-muted">{entities.length}</span>
      </div>

      <details className="mt-3 rounded-lg border border-card-border bg-dropzone p-3 text-xs text-muted">
        <summary className="cursor-pointer font-medium text-ink">
          Was bedeuten die Entity-Typen?
        </summary>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1">
          {ENTITY_TYPE_LEGEND.map((item) => (
            <div key={item.type} className="contents">
              <dt className="font-medium text-ink">{item.type}</dt>
              <dd>{item.description}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2">
          Confidence ist der Score des Recognizers (kein Wahrheitsbeweis); der Recognizer ist das
          Modul/die Regel/das Modell, das die Entity erkannt hat.
        </p>
      </details>

      {stale && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          Dieses PII-Ergebnis gehört zu einem älteren Textstand und wird nicht im Text markiert.
        </p>
      )}
      {entities.length === 0 ? (
        <p className="mt-4 text-sm text-muted">Keine Entities erkannt.</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {entities.map((entity) => (
            <PiiEntityCard
              key={entity.id}
              entity={entity}
              documentId={documentId}
              artifactId={artifactId}
              feedbackEnabled={feedbackEnabled}
              existingStatus={feedbackStatuses[entityFeedbackKey(entity)] ?? null}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
