import { useEffect, useState } from "react";

import {
  PII_REVIEW_DECISION_OPTIONS,
  fetchPiiReview,
  reviewStatusLabel,
  submitPiiReviewDecision,
  type PiiReviewDecisionScope,
  type PiiReviewDecisionValue,
  type PiiReviewOccurrence,
  type PiiReviewResult,
  type PiiReviewStatus,
} from "../../api/piiReview";

interface PiiReviewGroupListProps {
  documentId: string;
  review: PiiReviewResult | null;
  /** Called with the freshly-fetched review result after a decision is persisted, so the caller
   *  (e.g. text-highlight suppression) can stay in sync without a full page reload. */
  onReviewChanged: (review: PiiReviewResult) => void;
  /** An occurrence id selected elsewhere (e.g. a clicked text highlight); expands and scrolls to
   *  its entity group. */
  selectedOccurrenceId?: string | null;
}

const STATUS_STYLES: Record<PiiReviewStatus, string> = {
  pending: "text-accent-dark",
  accepted: "text-emerald-700",
  rejected: "text-red-700",
  ignored: "text-muted",
};

function groupElementId(entityGroupId: string): string {
  return `pii-group-${entityGroupId}`;
}

function flashGroup(entityGroupId: string): void {
  const target = document.getElementById(groupElementId(entityGroupId));
  if (!target) {
    return;
  }
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.remove("pii-jump-flash");
  void target.offsetWidth;
  target.classList.add("pii-jump-flash");
}

/**
 * Grouped PII review list (PII L11 grouping + the Review L8 decision overlay): one row per entity
 * group with its occurrence count, reading-text projection coverage, and current decision, plus an
 * expandable per-occurrence list for an individual override. Never shows raw entity text — only
 * type, counts, and offsets, mirroring what the existing detection list already exposes safely.
 */
export function PiiReviewGroupList({
  documentId,
  review,
  onReviewChanged,
  selectedOccurrenceId,
}: PiiReviewGroupListProps) {
  const [savingTarget, setSavingTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedGroupId, setExpandedGroupId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedOccurrenceId || !review) {
      return;
    }
    const occurrence = review.occurrences.find((o) => o.occurrence_id === selectedOccurrenceId);
    if (!occurrence) {
      return;
    }
    setExpandedGroupId(occurrence.entity_group_id);
    flashGroup(occurrence.entity_group_id);
  }, [selectedOccurrenceId, review]);

  if (!review || review.groups.length === 0) {
    return null;
  }

  const occurrencesByGroup = new Map<string, PiiReviewOccurrence[]>();
  for (const occurrence of review.occurrences) {
    const list = occurrencesByGroup.get(occurrence.entity_group_id) ?? [];
    list.push(occurrence);
    occurrencesByGroup.set(occurrence.entity_group_id, list);
  }

  async function submit(
    targetType: PiiReviewDecisionScope,
    targetId: string,
    decision: PiiReviewDecisionValue,
  ) {
    setSavingTarget(targetId);
    setError(null);
    try {
      await submitPiiReviewDecision(documentId, {
        target_type: targetType,
        target_id: targetId,
        decision,
      });
      const updated = await fetchPiiReview(documentId);
      if (updated) {
        onReviewChanged(updated);
      }
    } catch {
      setError("Entscheidung konnte nicht gespeichert werden.");
    } finally {
      setSavingTarget(null);
    }
  }

  return (
    <section aria-labelledby="review-groups-heading" className="mt-6">
      <div className="flex items-center justify-between gap-3">
        <h2 id="review-groups-heading" className="font-semibold text-ink">
          Review-Entscheidungen
        </h2>
        <span className="text-xs text-muted">{review.groups.length}</span>
      </div>
      {error && <p className="mt-2 text-xs font-medium text-red-700">{error}</p>}
      <ul className="mt-4 space-y-3">
        {review.groups.map((group) => {
          const occurrences = occurrencesByGroup.get(group.entity_group_id) ?? [];
          const expanded = expandedGroupId === group.entity_group_id;
          return (
            <li
              key={group.entity_group_id}
              id={groupElementId(group.entity_group_id)}
              className="scroll-mt-16 rounded-lg border border-card-border bg-card p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <span className="rounded-full bg-accent-soft px-2 py-1 text-xs font-medium text-accent-dark">
                    {group.entity_type}
                  </span>
                  <span className="ml-2 text-xs text-muted">{group.occurrence_count}× erkannt</span>
                </div>
                <span className={`text-xs font-medium ${STATUS_STYLES[group.review_status]}`}>
                  {reviewStatusLabel(group.review_status)}
                </span>
              </div>
              <p className="mt-2 text-xs text-muted">
                Lesetext-Abdeckung: {group.projection_summary.exact_count} exakt ·{" "}
                {group.projection_summary.partial_count} teilweise ·{" "}
                {group.projection_summary.unmapped_count} nur Rohtext
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <label className="sr-only" htmlFor={`group-decision-${group.entity_group_id}`}>
                  Entscheidung für Gruppe
                </label>
                <select
                  id={`group-decision-${group.entity_group_id}`}
                  value={group.review_decision ?? ""}
                  disabled={savingTarget === group.entity_group_id}
                  onChange={(event) => {
                    const value = event.target.value as PiiReviewDecisionValue | "";
                    if (value) {
                      void submit("entity_group", group.entity_group_id, value);
                    }
                  }}
                  className="rounded-lg border border-card-border bg-dropzone px-2 py-1 text-xs text-ink"
                >
                  <option value="">Entscheidung wählen …</option>
                  {PII_REVIEW_DECISION_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                {occurrences.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setExpandedGroupId(expanded ? null : group.entity_group_id)}
                    className="text-xs font-medium text-accent-dark underline decoration-dotted underline-offset-2 hover:decoration-solid"
                  >
                    {expanded ? "Vorkommen ausblenden" : `Vorkommen anzeigen (${occurrences.length})`}
                  </button>
                )}
              </div>
              {occurrences.length > 0 && (
                <ul
                  className={`mt-3 space-y-2 border-t border-card-border pt-3 ${expanded ? "" : "hidden"}`}
                >
                  {occurrences.map((occurrence) => (
                    <li
                      key={occurrence.occurrence_id}
                      id={`pii-review-occurrence-${occurrence.occurrence_id}`}
                      className="scroll-mt-16 flex flex-wrap items-center justify-between gap-2 text-xs"
                    >
                      <span className="text-muted">
                        Offset {occurrence.raw_start}–{occurrence.raw_end}
                        {occurrence.decision_scope === "occurrence" ? " · individuell" : ""}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className={STATUS_STYLES[occurrence.review_status]}>
                          {reviewStatusLabel(occurrence.review_status)}
                        </span>
                        <label className="sr-only" htmlFor={`occurrence-decision-${occurrence.occurrence_id}`}>
                          Override für Vorkommen
                        </label>
                        <select
                          id={`occurrence-decision-${occurrence.occurrence_id}`}
                          value={
                            occurrence.decision_scope === "occurrence" && occurrence.review_decision
                              ? occurrence.review_decision
                              : ""
                          }
                          disabled={savingTarget === occurrence.occurrence_id}
                          onChange={(event) => {
                            const value = event.target.value as PiiReviewDecisionValue | "";
                            if (value) {
                              void submit("occurrence", occurrence.occurrence_id, value);
                            }
                          }}
                          className="rounded-lg border border-card-border bg-dropzone px-1 py-0.5 text-xs text-ink"
                        >
                          <option value="">Override …</option>
                          {PII_REVIEW_DECISION_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
