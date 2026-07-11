import { useState } from "react";

import type { PiiEntity } from "../../api/workstations";
import {
  PII_REVIEW_DECISION_OPTIONS,
  fetchPiiReview,
  reviewStatusLabel,
  submitPiiReviewDecision,
  type PiiReviewOccurrence,
  type PiiReviewResult,
  type PiiReviewDecisionValue,
} from "../../api/piiReview";
import {
  PII_FEEDBACK_ISSUE_OPTIONS,
  buildIssueFeedback,
  buildPositiveFeedback,
  issueExplanation,
  issueTypeLabel,
  sendPiiFeedback,
  type PiiFeedbackStatus,
  type PiiIssueOnly,
} from "../../api/piiFeedback";
import { scrollAndFlash } from "../../lib/scrollAndFlash";

interface PiiEntityCardProps {
  entity: PiiEntity;
  documentId: string;
  artifactId: string;
  /** Dev gate: when false, no feedback controls are shown at all. */
  feedbackEnabled: boolean;
  /** Feedback already recorded for this entity in this artifact, if any. */
  existingStatus: PiiFeedbackStatus | null;
  /** Binding review state for this exact detector occurrence. */
  reviewOccurrence?: PiiReviewOccurrence | null;
  onReviewChanged?: (review: PiiReviewResult) => void;
}

type SubmitState = "idle" | "saving" | "error";

const CONFIDENCE_HELP = "Score des Recognizers; kein Wahrheitsbeweis.";
const RECOGNIZER_HELP = "Modul/Regel/Modell, das diese Entity erkannt hat.";

/** Briefly scroll to and flash the highlighted span for this entity in the extracted-text view. */
function jumpToEntity(entityId: string): void {
  scrollAndFlash(`pii-mark-${entityId}`);
}

/**
 * One detected-entity card. When the dev gate is on it also carries review feedback: a "Passt"
 * button in the header and, below, an issue picker with an explanation and optional comment.
 * Once feedback exists (loaded or just saved) the card is locked to a status line so the same
 * feedback cannot be submitted twice for the same entity in the same artifact.
 */
export function PiiEntityCard({
  entity,
  documentId,
  artifactId,
  feedbackEnabled,
  existingStatus,
  reviewOccurrence = null,
  onReviewChanged,
}: PiiEntityCardProps) {
  const [saved, setSaved] = useState<PiiFeedbackStatus | null>(existingStatus);
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [issueType, setIssueType] = useState<PiiIssueOnly | "">("");
  const [comment, setComment] = useState("");
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewError, setReviewError] = useState(false);

  const locked = saved !== null;

  async function submitPositive() {
    if (locked || submitState === "saving") {
      return;
    }
    setSubmitState("saving");
    try {
      await sendPiiFeedback(documentId, buildPositiveFeedback(artifactId, entity));
      setSaved({ verdict: "positive", issue_type: "correct" });
      setSubmitState("idle");
    } catch {
      setSubmitState("error");
    }
  }

  async function submitIssue() {
    if (locked || issueType === "" || submitState === "saving") {
      return;
    }
    setSubmitState("saving");
    try {
      await sendPiiFeedback(
        documentId,
        buildIssueFeedback(artifactId, entity, issueType, comment),
      );
      setSaved({ verdict: "issue", issue_type: issueType });
      setSubmitState("idle");
    } catch {
      setSubmitState("error");
    }
  }

  async function submitReviewDecision(decision: PiiReviewDecisionValue) {
    if (!reviewOccurrence || reviewSaving) return;
    setReviewSaving(true);
    setReviewError(false);
    try {
      await submitPiiReviewDecision(documentId, {
        target_type: "occurrence",
        target_id: reviewOccurrence.occurrence_id,
        decision,
      });
      const updated = await fetchPiiReview(documentId);
      if (updated) onReviewChanged?.(updated);
    } catch {
      setReviewError(true);
    } finally {
      setReviewSaving(false);
    }
  }

  const selectedExplanation = issueType === "" ? undefined : issueExplanation(issueType);

  return (
    <li
      id={`pii-entity-card-${entity.id}`}
      className="scroll-mt-16 rounded-lg border border-card-border bg-dropzone p-3"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="rounded-full bg-accent-soft px-2 py-1 text-xs font-medium text-accent-dark">
          {entity.entity_type}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted" title={CONFIDENCE_HELP}>
            {(entity.score * 100).toFixed(0)} %
          </span>
          {feedbackEnabled && !locked && (
            <button
              type="button"
              onClick={() => void submitPositive()}
              disabled={submitState === "saving"}
              className="rounded-full bg-accent px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
            >
              Passt
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 break-words text-sm font-medium text-ink">{entity.text}</p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs text-muted">
        <dt>Seite</dt>
        <dd>{entity.page_number ?? "–"}</dd>
        <dt>Offset</dt>
        <dd>
          <button
            type="button"
            onClick={() => jumpToEntity(entity.id)}
            title="Im extrahierten Text zu dieser Stelle springen"
            className="font-medium text-accent-dark underline decoration-dotted underline-offset-2 hover:decoration-solid"
          >
            {entity.start_offset}–{entity.end_offset}
          </button>
        </dd>
        <dt title={RECOGNIZER_HELP}>Recognizer</dt>
        <dd className="break-all" title={RECOGNIZER_HELP}>
          {entity.recognizer}
        </dd>
      </dl>

      {reviewOccurrence && (
        <div className="mt-3 border-t border-card-border pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <span className="text-xs font-medium text-muted">Bindende Entscheidung</span>
              <p className="mt-0.5 text-xs text-accent-dark">
                {reviewStatusLabel(reviewOccurrence.review_status)}
                {reviewOccurrence.decision_scope === "occurrence" ? " · individuell" : ""}
              </p>
            </div>
            <label className="sr-only" htmlFor={`entity-decision-${entity.id}`}>
              Entscheidung für diese Entity
            </label>
            <select
              id={`entity-decision-${entity.id}`}
              value={reviewOccurrence.review_decision ?? "pseudonymize"}
              disabled={reviewSaving}
              onChange={(event) =>
                void submitReviewDecision(event.target.value as PiiReviewDecisionValue)
              }
              className="rounded-lg border border-card-border bg-card px-2 py-1 text-xs text-ink"
            >
              {PII_REVIEW_DECISION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          {reviewError && (
            <p className="mt-2 text-xs font-medium text-red-700">
              Entscheidung konnte nicht gespeichert werden.
            </p>
          )}
        </div>
      )}

      {feedbackEnabled && locked && saved && (
        <div className="mt-3 border-t border-card-border pt-3">
          <span className="text-xs font-medium text-accent-dark">
            Feedback gespeichert: {issueTypeLabel(saved.issue_type)}
          </span>
        </div>
      )}

      {feedbackEnabled && !locked && (
        <div className="mt-3 space-y-2 border-t border-card-border pt-3">
          <span className="text-xs font-medium text-muted">Review-Feedback (dev)</span>
          <label className="sr-only" htmlFor={`issue-${entity.id}`}>
            Problem auswählen
          </label>
          <select
            id={`issue-${entity.id}`}
            value={issueType}
            onChange={(event) => setIssueType(event.target.value as PiiIssueOnly | "")}
            className="w-full rounded-lg border border-card-border bg-card px-2 py-1 text-xs text-ink"
          >
            <option value="">Problem auswählen …</option>
            {PII_FEEDBACK_ISSUE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {selectedExplanation && (
            <p className="rounded-lg bg-accent-soft px-2 py-1 text-xs text-accent-dark">
              {selectedExplanation}
            </p>
          )}
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Kommentar (optional)"
            rows={2}
            className="w-full rounded-lg border border-card-border bg-card px-2 py-1 text-xs text-ink"
          />
          <p className="text-xs text-muted">
            Do not paste document text or raw PII into comments.
          </p>
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => void submitIssue()}
              disabled={issueType === "" || submitState === "saving"}
              className="rounded-lg border border-card-border px-3 py-1 text-xs font-medium text-ink disabled:opacity-50"
            >
              Feedback speichern
            </button>
            {submitState === "error" && (
              <span className="text-xs font-medium text-red-700">
                Konnte nicht gespeichert werden
              </span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
