import type { PiiEntity } from "../../api/workstations";
import { PiiEntityFeedback } from "./PiiEntityFeedback";

interface PiiEntityListProps {
  entities: readonly PiiEntity[];
  stale: boolean;
  documentId: string;
  /** Id of the PII artifact these entities belong to; used to attach feedback. */
  artifactId: string;
  /** Dev gate: when false, per-entity feedback controls are hidden. */
  feedbackEnabled: boolean;
}

export function PiiEntityList({
  entities,
  stale,
  documentId,
  artifactId,
  feedbackEnabled,
}: PiiEntityListProps) {
  return (
    <section aria-labelledby="entity-list-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="entity-list-heading" className="font-semibold text-ink">
          Erkannte Entities
        </h2>
        <span className="text-xs text-muted">{entities.length}</span>
      </div>
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
            <li key={entity.id} className="rounded-lg border border-card-border bg-dropzone p-3">
              <div className="flex items-start justify-between gap-3">
                <span className="rounded-full bg-accent-soft px-2 py-1 text-xs font-medium text-accent-dark">
                  {entity.entity_type}
                </span>
                <span className="text-xs font-medium text-muted">
                  {(entity.score * 100).toFixed(0)} %
                </span>
              </div>
              <p className="mt-2 break-words text-sm font-medium text-ink">{entity.text}</p>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs text-muted">
                <dt>Seite</dt>
                <dd>{entity.page_number ?? "–"}</dd>
                <dt>Offset</dt>
                <dd>
                  {entity.start_offset}–{entity.end_offset}
                </dd>
                <dt>Recognizer</dt>
                <dd className="break-all">{entity.recognizer}</dd>
              </dl>
              <PiiEntityFeedback
                documentId={documentId}
                artifactId={artifactId}
                entity={entity}
                enabled={feedbackEnabled}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
