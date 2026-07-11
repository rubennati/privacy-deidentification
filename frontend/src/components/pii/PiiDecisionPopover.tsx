import { useEffect, useRef, useState } from "react";

import {
  PII_REVIEW_DECISION_OPTIONS,
  fetchPiiReview,
  reviewStatusLabel,
  submitPiiReviewDecision,
  type PiiReviewDecisionScope,
  type PiiReviewDecisionValue,
  type PiiReviewResult,
  type PiiReviewStatus,
} from "../../api/piiReview";
import { entityTypeLabel } from "../../lib/entityTypeLabels";

/** What the user clicked in the text, already resolved by the caller against the current review
 *  result: a detected entity's group (a decision applies to all its occurrences), a single
 *  occurrence that already carries an individual override, or a manual addition. */
export interface PiiDecisionTarget {
  scope: PiiReviewDecisionScope;
  targetId: string;
  entityType: string;
  occurrenceCount: number;
  reviewStatus: PiiReviewStatus;
  currentDecision: PiiReviewDecisionValue;
}

interface PiiDecisionPopoverProps {
  documentId: string;
  target: PiiDecisionTarget;
  /** Viewport-space rect of the clicked highlight, used to anchor the popover (position: fixed). */
  anchorRect: { top: number; bottom: number; left: number; width: number };
  onClose: () => void;
  /** Called with the freshly-fetched review result after a decision is persisted. */
  onReviewChanged: (review: PiiReviewResult) => void;
}

const POPOVER_WIDTH = 288;

const STATUS_BADGE_STYLES: Record<PiiReviewStatus, string> = {
  accepted: "bg-accent-soft text-accent-dark",
  kept: "bg-slate-100 text-slate-700",
  rejected: "bg-slate-100 text-slate-500",
};

/**
 * In-place review decision for the user view: opens next to a clicked highlight and offers exactly
 * the two decisions that would change something — the current state is shown, not offered again.
 * Decisions go through the same review endpoint the (dev-view) group list uses; nothing new is
 * persisted client-side.
 */
export function PiiDecisionPopover({
  documentId,
  target,
  anchorRect,
  onClose,
  onReviewChanged,
}: PiiDecisionPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Close on Escape, on any click outside the popover, and on scroll (the fixed-position anchor
  // would otherwise drift away from its highlight).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    function onPointerDown(event: PointerEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        onClose();
      }
    }
    function onScroll(event: Event) {
      if (popoverRef.current && event.target instanceof Node && popoverRef.current.contains(event.target)) {
        return;
      }
      onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onClose);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  const alternatives = PII_REVIEW_DECISION_OPTIONS.filter(
    (option) => option.value !== target.currentDecision,
  );

  async function decide(decision: PiiReviewDecisionValue) {
    setSaving(true);
    setError(null);
    try {
      await submitPiiReviewDecision(documentId, {
        target_type: target.scope,
        target_id: target.targetId,
        decision,
      });
      const updated = await fetchPiiReview(documentId);
      if (updated) {
        onReviewChanged(updated);
      }
      onClose();
    } catch {
      setError("Entscheidung konnte nicht gespeichert werden.");
      setSaving(false);
    }
  }

  const left = Math.max(
    8,
    Math.min(
      anchorRect.left + anchorRect.width / 2 - POPOVER_WIDTH / 2,
      window.innerWidth - POPOVER_WIDTH - 8,
    ),
  );
  // Prefer below the highlight; flip above when there is clearly not enough room.
  const openAbove = window.innerHeight - anchorRect.bottom < 180 && anchorRect.top > 200;

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label={`Entscheidung für ${entityTypeLabel(target.entityType)}`}
      data-testid="pii-decision-popover"
      className="fixed z-50 rounded-xl border border-card-border bg-card p-3 shadow-[0_8px_30px_rgba(17,24,39,0.16)]"
      style={{
        width: POPOVER_WIDTH,
        left,
        ...(openAbove
          ? { bottom: window.innerHeight - anchorRect.top + 8 }
          : { top: anchorRect.bottom + 8 }),
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink">{entityTypeLabel(target.entityType)}</p>
          <p className="mt-0.5 text-xs text-muted">
            {target.scope === "manual_addition"
              ? "Manuell hinzugefügt"
              : target.scope === "occurrence"
                ? "Gilt nur für dieses Vorkommen"
                : target.occurrenceCount > 1
                  ? `${target.occurrenceCount}× im Dokument · Entscheidung gilt für alle Vorkommen`
                  : "1× im Dokument"}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Schließen"
          className="rounded-md px-1.5 text-lg leading-none text-muted hover:text-ink"
        >
          ×
        </button>
      </div>

      <p className="mt-2">
        <span
          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE_STYLES[target.reviewStatus]}`}
        >
          {reviewStatusLabel(target.reviewStatus)}
        </span>
      </p>

      <div className="mt-3 flex flex-col gap-2">
        {alternatives.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={saving}
            onClick={() => void decide(option.value)}
            className="rounded-lg border border-card-border bg-dropzone px-3 py-1.5 text-left text-sm font-medium text-ink transition-colors hover:border-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
          >
            {option.label}
          </button>
        ))}
      </div>

      {error && <p className="mt-2 text-xs font-medium text-red-700">{error}</p>}
    </div>
  );
}
