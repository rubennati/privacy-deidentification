import { useEffect, useState } from "react";

import {
  addPiiManualEntity,
  fetchPiiReview,
  type PiiReviewResult,
} from "../../api/piiReview";
import { entityTypeLabel } from "../../lib/entityTypeLabels";

interface AddPiiManualEntityProps {
  documentId: string;
  /** The running profile's configured entity types (PiiContent.configured_entity_types) — the
   *  picker never offers a type outside what this PII run was configured to detect (ADR-0035). */
  entityTypes: readonly string[];
  readingText: string;
  selection: { start: number; end: number } | null;
  onAdded: (review: PiiReviewResult) => void;
}

const PREVIEW_LIMIT = 120;

/**
 * The "add a missed entity" panel (PII L14 / Review L10, ADR-0035): appears once the reader selects
 * a non-empty span in the canonical reading-text view, shows a read-only preview of that selection,
 * lets the reviewer pick an entity type, and submits it as a new manual addition. Renders nothing
 * without a current selection.
 */
export function AddPiiManualEntity({
  documentId,
  entityTypes,
  readingText,
  selection,
  onAdded,
}: AddPiiManualEntityProps) {
  const [entityType, setEntityType] = useState<string>(entityTypes[0] ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (entityTypes.length > 0 && !entityTypes.includes(entityType)) {
      setEntityType(entityTypes[0]);
    }
  }, [entityTypes, entityType]);

  useEffect(() => {
    setError(null);
  }, [selection]);

  if (!selection) {
    return null;
  }

  const preview = readingText.slice(selection.start, selection.end);
  const truncatedPreview =
    preview.length > PREVIEW_LIMIT ? `${preview.slice(0, PREVIEW_LIMIT)}…` : preview;

  async function handleSubmit() {
    if (!selection || !entityType) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await addPiiManualEntity(documentId, {
        entity_type: entityType,
        canonical_start: selection.start,
        canonical_end: selection.end,
      });
      const updated = await fetchPiiReview(documentId);
      if (updated) {
        onAdded(updated);
      }
    } catch {
      setError("Ergänzung konnte nicht gespeichert werden.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="region"
      aria-label="Als PII hinzufügen"
      className="mt-3 rounded-lg border border-card-border bg-card p-3 shadow-[0_8px_30px_rgba(17,24,39,0.16)]"
    >
      <p className="text-xs text-muted">
        Auswahl: <span className="font-medium text-ink">„{truncatedPreview}“</span>
      </p>
      {error && <p className="mt-2 text-xs font-medium text-red-700">{error}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="manual-addition-entity-type">
          Entity-Typ
        </label>
        <select
          id="manual-addition-entity-type"
          value={entityType}
          disabled={saving || entityTypes.length === 0}
          onChange={(event) => setEntityType(event.target.value)}
          className="rounded-lg border border-card-border bg-dropzone px-2 py-1 text-xs text-ink"
        >
          {entityTypes.map((type) => (
            <option key={type} value={type}>
              {entityTypeLabel(type)}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={saving || !entityType}
          className="rounded-lg bg-accent px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          Als PII hinzufügen
        </button>
      </div>
    </div>
  );
}
