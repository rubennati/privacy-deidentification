import { useState } from "react";

import type { PiiEntity } from "../../api/workstations";
import {
  PII_FEEDBACK_ISSUE_OPTIONS,
  buildIssueFeedback,
  buildPositiveFeedback,
  sendPiiFeedback,
  type PiiFeedbackIssueType,
} from "../../api/piiFeedback";

interface PiiEntityFeedbackProps {
  documentId: string;
  artifactId: string;
  entity: PiiEntity;
  /** Dev gate. When false the whole control set is hidden and nothing can be sent. */
  enabled: boolean;
}

type Status = "idle" | "saving" | "saved" | "error";

type IssueValue = Exclude<PiiFeedbackIssueType, "correct"> | "";

/**
 * Dev-only review feedback controls for one detected entity: a "Passt" (positive) button plus a
 * small issue picker with an optional comment. Renders nothing unless the dev gate is enabled.
 * Saving updates a transient inline status; it never reloads the page or mutates the entity list.
 */
export function PiiEntityFeedback({
  documentId,
  artifactId,
  entity,
  enabled,
}: PiiEntityFeedbackProps) {
  const [status, setStatus] = useState<Status>("idle");
  const [issueType, setIssueType] = useState<IssueValue>("");
  const [comment, setComment] = useState("");

  if (!enabled) {
    return null;
  }

  async function submitPositive() {
    setStatus("saving");
    try {
      await sendPiiFeedback(documentId, buildPositiveFeedback(artifactId, entity));
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  async function submitIssue() {
    if (issueType === "") {
      return;
    }
    setStatus("saving");
    try {
      await sendPiiFeedback(
        documentId,
        buildIssueFeedback(artifactId, entity, issueType, comment),
      );
      setStatus("saved");
      setIssueType("");
      setComment("");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="mt-3 border-t border-card-border pt-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted">Review-Feedback (dev)</span>
        <button
          type="button"
          onClick={() => void submitPositive()}
          disabled={status === "saving"}
          className="rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent-dark disabled:opacity-50"
        >
          Passt
        </button>
      </div>
      <div className="mt-2 space-y-2">
        <label className="sr-only" htmlFor={`issue-${entity.id}`}>
          Problem auswählen
        </label>
        <select
          id={`issue-${entity.id}`}
          value={issueType}
          onChange={(event) => setIssueType(event.target.value as IssueValue)}
          className="w-full rounded-lg border border-card-border bg-card px-2 py-1 text-xs text-ink"
        >
          <option value="">Problem auswählen …</option>
          {PII_FEEDBACK_ISSUE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          placeholder="Kommentar (optional)"
          rows={2}
          className="w-full rounded-lg border border-card-border bg-card px-2 py-1 text-xs text-ink"
        />
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => void submitIssue()}
            disabled={issueType === "" || status === "saving"}
            className="rounded-lg border border-card-border px-3 py-1 text-xs font-medium text-ink disabled:opacity-50"
          >
            Feedback speichern
          </button>
          {status === "saved" && (
            <span className="text-xs font-medium text-accent-dark">Feedback gespeichert</span>
          )}
          {status === "error" && (
            <span className="text-xs font-medium text-red-700">
              Konnte nicht gespeichert werden
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
