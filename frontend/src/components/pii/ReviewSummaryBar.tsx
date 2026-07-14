import type { PiiReviewResult, PiiReviewStatus } from "../../api/piiReview";

interface ReviewSummaryBarProps {
  review: PiiReviewResult;
  /** Jump to the previous/next highlight in the current text view; the buttons render only when
   *  this is provided (i.e. there is at least one visible mark to jump to). */
  onNavigate?: (direction: "prev" | "next") => void;
}

const NAV_BUTTON =
  "rounded-md border border-card-border bg-card px-2 py-0.5 text-sm leading-none text-muted transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none";

/**
 * User-view replacement for the former review sidebar: one quiet line of counts plus a legend that
 * explains the three in-text highlight states. All decisions happen directly on the highlights
 * (see PiiDecisionPopover); this bar only summarizes them.
 */
export function ReviewSummaryBar({ review, onNavigate }: ReviewSummaryBarProps) {
  const counts: Record<PiiReviewStatus, number> = { accepted: 0, kept: 0, rejected: 0 };
  let total = 0;
  for (const occurrence of review.occurrences) {
    counts[occurrence.review_status] += 1;
    total += 1;
  }
  for (const addition of review.manual_additions) {
    // Stale additions refer to a superseded text and are not rendered as highlights.
    if (addition.artifact_currency === "stale") {
      continue;
    }
    counts[addition.review_status] += 1;
    total += 1;
  }

  if (total === 0) {
    return null;
  }

  return (
    <div
      data-testid="review-summary-bar"
      className="mb-5 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-lg bg-dropzone px-4 py-2.5"
    >
      <div className="flex items-center gap-3">
        <p className="text-sm text-ink">
          <span className="font-semibold">{total}</span> sensible{" "}
          {total === 1 ? "Stelle" : "Stellen"} erkannt
        </p>
        {onNavigate && (
          <span className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onNavigate("prev")}
              aria-label="Zur vorherigen Fundstelle springen"
              title="Vorherige Fundstelle"
              className={NAV_BUTTON}
            >
              ↑
            </button>
            <button
              type="button"
              onClick={() => onNavigate("next")}
              aria-label="Zur nächsten Fundstelle springen"
              title="Nächste Fundstelle"
              className={NAV_BUTTON}
            >
              ↓
            </button>
          </span>
        )}
      </div>
      <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted">
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-3 w-3 rounded-sm bg-amber-200" />
          Wird pseudonymisiert ({counts.accepted})
        </li>
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-3 w-3 rounded-sm bg-card ring-1 ring-inset ring-slate-400"
          />
          Bleibt unverändert ({counts.kept})
        </li>
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-3 w-3 rounded-sm bg-card [outline:1.5px_dashed_#a8b0a4] [outline-offset:-1.5px]"
          />
          Kein PII ({counts.rejected})
        </li>
      </ul>
    </div>
  );
}
