import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { fetchAppConfig, type AppConfig } from "../api/config";
import { DocumentsApiError, fetchDocument, type DocumentSummary } from "../api/documents";
import {
  fetchAudit,
  fetchDocumentJobs,
  fetchJobStatus,
  fetchOcr,
  fetchPii,
  runAudit,
  runOcr,
  runPii,
  type AuditArtifact,
  type JobStatus,
  type PiiArtifact,
  type PiiRunRequest,
  type TextArtifact,
  WorkstationApiError,
} from "../api/workstations";
import { jobActivityStore, resumeActiveJobs } from "../lib/jobActivity";
import { JobStatusBanner } from "../components/JobStatusBanner";
import {
  buildFeedbackStatusMap,
  fetchPiiFeedbackSummary,
  type PiiFeedbackStatus,
} from "../api/piiFeedback";
import {
  fetchPiiReview,
  reviewDecisionLabel,
  submitPiiReviewDecision,
  type PiiReviewDecisionValue,
  type PiiReviewResult,
} from "../api/piiReview";
import {
  fetchPiiEntityContract,
  type PiiEntityContractV1,
} from "../api/piiEntityContract";
import { AddPiiManualEntity } from "../components/pii/AddPiiManualEntity";
import {
  PiiDecisionPopover,
  type PiiDecisionTarget,
} from "../components/pii/PiiDecisionPopover";
import { PiiEntityList } from "../components/pii/PiiEntityList";
import { PiiReviewGroupList } from "../components/pii/PiiReviewGroupList";
import { ReviewSummaryBar } from "../components/pii/ReviewSummaryBar";
import { PiiEngineSettingsPanel } from "../components/pii/PiiEngineSettingsPanel";
import { PiiValidationTransparency } from "../components/pii/PiiValidationTransparency";
import {
  ReviewTextViewer,
  type ReviewTextMode,
} from "../components/pii/ReviewTextViewer";
import {
  StationPanel,
  type StationStatus,
} from "../components/workstations/StationPanel";
import { StatusNotice } from "../components/StatusNotice";
import { Toast } from "../components/Toast";
import { DocumentAnalysisPanel } from "../components/DocumentAnalysisPanel";
import { ViewModeToggle, type ViewMode } from "../components/ViewModeToggle";
import {
  isAnalysisRunning,
  runDocumentAnalysis,
  type AnalysisStep,
} from "../lib/documentAnalysis";
import { toStationError, type StationName } from "../lib/stationErrors";
import { buildRuntimeNotice, buildStationRuntimeNotice } from "../lib/runtimeNotice";
import { buildAnchorBoundPiiHighlights, buildManualAdditionHighlights } from "../lib/piiHighlights";
import { scrollAndFlash } from "../lib/scrollAndFlash";
import { formatBytes, formatTimestamp } from "../lib/format";

interface UiError {
  message: string;
  correlationId: string | null;
}

// A new run never deletes existing artifacts — it appends a new immutable one — so
// "erneut erstellen" (create again) is the correct verb, not "Reset".
const RERUN_HINT =
  "Ein erneuter Lauf erzeugt ein neues Ergebnis. Vorherige Ergebnisse bleiben als Artefakte erhalten.";
const DEV_PII_HINT =
  "Ein neuer Lauf erzeugt ein neues Ergebnis. Ein gewähltes Dev-Profil gilt nur für diesen Lauf.";

export default function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [document, setDocument] = useState<DocumentSummary | null>(null);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [audit, setAudit] = useState<AuditArtifact | null>(null);
  const [text, setText] = useState<TextArtifact | null>(null);
  const [pii, setPii] = useState<PiiArtifact | null>(null);
  const [feedbackStatuses, setFeedbackStatuses] = useState<Record<string, PiiFeedbackStatus>>({});
  const [reviewResult, setReviewResult] = useState<PiiReviewResult | null>(null);
  const [piiEntityContractState, setPiiEntityContractState] = useState<
    | { status: "idle" | "loading" | "not_found" | "incompatible" | "error" }
    | { status: "ok"; contract: PiiEntityContractV1 }
  >({ status: "idle" });
  const [selectedOccurrenceId, setSelectedOccurrenceId] = useState<string | null>(null);
  // User-view in-place decision: which highlight was clicked and where its mark sits on screen.
  // The decidable target itself is re-resolved from the current review result on every render, so
  // a decision or re-run can never leave a stale popover open against outdated data.
  const [decisionAnchor, setDecisionAnchor] = useState<{
    entityId: string;
    rect: { top: number; bottom: number; left: number; width: number };
  } | null>(null);
  // One quiet confirmation after an in-place decision, with a one-shot undo. Never more than one.
  const [toast, setToast] = useState<{ message: string; undo?: () => Promise<void> } | null>(null);
  // Position of the ↑/↓ jump navigation through the currently visible highlights; -1 = not started.
  const navPosition = useRef(-1);
  const [reviewTextMode, setReviewTextMode] = useState<ReviewTextMode>("reading");
  const [selectedTextRange, setSelectedTextRange] = useState<{
    start: number;
    end: number;
  } | null>(null);
  const [analysisStep, setAnalysisStep] = useState<AnalysisStep>("idle");
  const [analysisError, setAnalysisError] = useState<UiError | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("user");
  const [selectedPiiProfile, setSelectedPiiProfile] = useState("");
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<UiError | null>(null);
  const [stationErrors, setStationErrors] = useState<Record<StationName, UiError | null>>({
    audit: null,
    ocr: null,
    pii: null,
  });
  const [pending, setPending] = useState<Record<StationName, boolean>>({
    audit: false,
    ocr: false,
    pii: false,
  });
  // Runtime Job UX v1: the newest tracked OCR job for this document, sourced from the shared
  // job-activity store (localStorage + backend fallback), independent of any locally in-flight
  // call. This is what lets a reloaded page show "still running"/"finished while you were away"
  // instead of silently looking idle.
  const [trackedOcrJob, setTrackedOcrJob] = useState<JobStatus | null>(null);
  const [trackedOcrJobPollFailure, setTrackedOcrJobPollFailure] = useState<string | null>(null);
  const [ocrResultLoadError, setOcrResultLoadError] = useState(false);
  const handledOcrJobIds = useRef(new Set<string>());

  useEffect(() => {
    let active = true;
    if (!documentId) {
      setPageError({ message: "Dokument nicht gefunden.", correlationId: null });
      setLoading(false);
      return () => {
        active = false;
      };
    }
    setSelectedPiiProfile("");
    // Identity transition fail-closed: private text and all derived state leave the DOM before the
    // next document request starts, never after it happens to finish.
    setDocument(null);
    setAudit(null);
    setText(null);
    setPii(null);
    setReviewResult(null);
    setDecisionAnchor(null);
    setToast(null);
    navPosition.current = -1;
    setPiiEntityContractState({ status: "idle" });
    setLoading(true);
    setReviewTextMode("reading");
    setSelectedTextRange(null);
    setAnalysisStep("idle");
    setAnalysisError(null);

    void (async () => {
      try {
        const [loadedDocument, loadedConfig] = await Promise.all([
          fetchDocument(documentId),
          fetchAppConfig(),
        ]);
        if (!active) return;
        setDocument(loadedDocument);
        setAppConfig(loadedConfig);

        const [auditResult, textResult, piiResult] = await Promise.all([
          loadOptional(() => fetchAudit(documentId), "audit"),
          loadOptional(() => fetchOcr(documentId), "ocr"),
          loadOptional(() => fetchPii(documentId), "pii"),
        ]);
        if (!active) return;
        setAudit(auditResult.data);
        setText(textResult.data);
        setPii(piiResult.data);
        setStationErrors({
          audit: auditResult.error,
          ocr: textResult.error,
          pii: piiResult.error,
        });
      } catch (error) {
        if (active) setPageError(toDocumentError(error));
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [documentId]);

  // Restore per-entity feedback state for the current PII artifact when the dev gate is on.
  const devGateEnabled = appConfig?.devEngineSettingsEnabled ?? false;
  const piiArtifactId = pii?.id ?? null;
  const piiTextArtifactId = pii?.input_text_artifact_id ?? null;
  useEffect(() => {
    if (!documentId || !piiArtifactId || !devGateEnabled) {
      setFeedbackStatuses({});
      return;
    }
    let active = true;
    void fetchPiiFeedbackSummary(documentId, piiArtifactId).then((summary) => {
      if (active) setFeedbackStatuses(buildFeedbackStatusMap(summary));
    });
    return () => {
      active = false;
    };
  }, [documentId, piiArtifactId, devGateEnabled]);

  // The review-entity overlay (groups + decisions) is not dev-gated; restore it whenever the
  // current PII artifact changes so highlight suppression stays correct after a re-run.
  useEffect(() => {
    setSelectedOccurrenceId(null);
    if (!documentId || !piiArtifactId) {
      setReviewResult(null);
      setPiiEntityContractState({ status: "idle" });
      return;
    }
    if (!text || piiTextArtifactId !== text.id) {
      setPiiEntityContractState({ status: "idle" });
      return;
    }
    let active = true;
    setPiiEntityContractState({ status: "loading" });
    void Promise.all([
      fetchPiiReview(documentId),
      fetchPiiEntityContract(documentId, piiArtifactId, text.id),
    ])
      .then(([review, contractResult]) => {
        if (!active) return;
        setReviewResult(review);
        setPiiEntityContractState(contractResult);
      })
      .catch(() => {
        if (active) setPiiEntityContractState({ status: "error" });
      });
    return () => {
      active = false;
    };
  }, [documentId, piiArtifactId, piiTextArtifactId, text]);

  const refreshPiiReviewAndContract = async (review: PiiReviewResult) => {
    setReviewResult(review);
    if (!documentId || !piiArtifactId) {
      setPiiEntityContractState({ status: "idle" });
      return;
    }
    if (!text || pii?.input_text_artifact_id !== text.id) {
      setPiiEntityContractState({ status: "idle" });
      return;
    }
    setPiiEntityContractState({ status: "loading" });
    const contractResult = await fetchPiiEntityContract(documentId, piiArtifactId, text.id);
    setPiiEntityContractState(contractResult);
  };

  // Reload recovery: rehydrate any tracked OCR job for this document and resume polling it (a
  // no-op if a live `runOcr` call already owns polling — see jobActivity's try-lock), then keep the
  // banner in sync with every subsequent update the shared store observes.
  useEffect(() => {
    if (!documentId) {
      setTrackedOcrJob(null);
      return;
    }
    const syncFromStore = () => {
      const [latestOcrJob] = jobActivityStore
        .list(documentId)
        .filter((job) => job.kind === "ocr_text");
      setTrackedOcrJob(latestOcrJob ?? null);
      setTrackedOcrJobPollFailure(
        latestOcrJob ? (jobActivityStore.getPollFailure(latestOcrJob.job_id) ?? null) : null,
      );
    };
    syncFromStore();
    const unsubscribe = jobActivityStore.subscribe(syncFromStore);
    resumeActiveJobs(jobActivityStore, documentId, fetchJobStatus, fetchDocumentJobs);
    return unsubscribe;
  }, [documentId]);

  // Only act on the tracked job when nothing on this page is already driving its own progress UI
  // for it (a live click-triggered run already applies its own result via onText/onPii and would
  // otherwise be double-fetched here). Each terminal job id is only ever handled once.
  const noLocalOcrRunInFlight = !pending.ocr && !isAnalysisRunning(analysisStep);
  useEffect(() => {
    if (!documentId || !trackedOcrJob || !noLocalOcrRunInFlight) {
      return;
    }
    if (handledOcrJobIds.current.has(trackedOcrJob.job_id)) {
      return;
    }
    if (trackedOcrJob.status === "succeeded") {
      handledOcrJobIds.current.add(trackedOcrJob.job_id);
      setOcrResultLoadError(false);
      if (!trackedOcrJob.result_artifact_id) {
        setOcrResultLoadError(true);
        return;
      }
      void fetchOcr(documentId, trackedOcrJob.result_artifact_id)
        .then((result) => {
          setText(result);
          setReviewTextMode("reading");
        })
        .catch(() => setOcrResultLoadError(true));
    } else if (trackedOcrJob.status === "failed" || trackedOcrJob.status === "canceled") {
      handledOcrJobIds.current.add(trackedOcrJob.job_id);
      setStationErrors((current) => ({
        ...current,
        ocr: {
          message:
            trackedOcrJob.error_message && trackedOcrJob.error_message !== ""
              ? trackedOcrJob.error_message
              : "Die OCR-Verarbeitung ist fehlgeschlagen.",
          correlationId: null,
        },
      }));
    }
  }, [documentId, trackedOcrJob, noLocalOcrRunInFlight]);

  // Auto-dismiss the decision toast after a few seconds; closing keeps the applied decision.
  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(timer);
  }, [toast]);

  // The user-view analysis action: run the existing Audit → OCR → PII stations in order via the
  // shared orchestration, applying each returned artifact as it arrives so a later failure keeps
  // the earlier results. Backend lineage validation stays authoritative; no IDs are constructed.
  const runUserAnalysis = async () => {
    if (!documentId || isAnalysisRunning(analysisStep)) {
      return;
    }
    setAnalysisError(null);
    // Tracks the station currently in flight so a failure maps to a safe, station-specific message.
    let activeStation: StationName = "audit";
    try {
      await runDocumentAnalysis(documentId, {
        onStep: (step) => {
          setAnalysisStep(step);
          if (step === "audit" || step === "ocr" || step === "pii") {
            activeStation = step;
          }
        },
        onAudit: setAudit,
        onText: (result) => {
          setText(result);
          setReviewTextMode("reading");
        },
        onPii: setPii,
      });
    } catch (error) {
      setAnalysisStep("idle");
      setAnalysisError(toStationError(error, activeStation));
    }
  };

  // Auto-start the analysis when arriving fresh from the upload page (router state, set exactly
  // there). The state is cleared via replace before the run starts, so a reload, back/forward
  // revisit, or copied URL never re-triggers an analysis; the ref guards the effect re-running
  // while its own state updates are still in flight.
  const autoAnalyzeRequested = Boolean(
    (location.state as { autoAnalyze?: boolean } | null)?.autoAnalyze,
  );
  const autoAnalyzeTriggered = useRef(false);
  useEffect(() => {
    if (autoAnalyzeTriggered.current || !autoAnalyzeRequested || loading || !document) {
      return;
    }
    autoAnalyzeTriggered.current = true;
    navigate(location.pathname, { replace: true, state: null });
    void runUserAnalysis();
    // runUserAnalysis is intentionally not a dependency: it is recreated per render, and the ref
    // above already guarantees a single trigger per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAnalyzeRequested, loading, document, navigate, location.pathname]);

  if (loading) {
    return (
      <div className="px-4 py-12 sm:px-6">
        <p className="mx-auto max-w-6xl text-sm text-muted">Dokument wird geladen …</p>
      </div>
    );
  }

  if (!document || !documentId) {
    return (
      <div className="px-4 py-12 sm:px-6">
        <div className="mx-auto max-w-2xl">
          <Link to="/documents" className="text-sm font-medium text-accent-dark hover:underline">
            ← Zurück zu Dokumenten
          </Link>
          <StatusNotice
            status="error"
            message={pageError?.message ?? "Dokument nicht gefunden."}
            correlationId={pageError?.correlationId}
          />
        </div>
      </div>
    );
  }

  const auditStatus: StationStatus = !audit
    ? "missing"
    : audit.input_artifact_id === document.original_artifact?.id
      ? "current"
      : "stale";
  const ocrStatus: StationStatus = !text
    ? "missing"
    : audit && text.input_audit_artifact_id === audit.id
      ? "current"
      : "stale";
  const piiStatus: StationStatus = !pii
    ? "missing"
    : text && pii.input_text_artifact_id === text.id
      ? "current"
      : "stale";
  const currentPiiEntityContract =
    piiStatus === "current" &&
    piiEntityContractState.status === "ok" &&
    piiEntityContractState.contract.pii_artifact_id === piiArtifactId &&
    piiEntityContractState.contract.text_artifact_id === text?.id
      ? piiEntityContractState.contract
      : null;
  const highlightModel = buildAnchorBoundPiiHighlights(currentPiiEntityContract);
  // Ordered ↑/↓ jump targets: exactly the marks visible in the active text view, by position.
  const manualHighlightViews = buildManualAdditionHighlights(reviewResult?.manual_additions ?? []);
  const visibleHighlights =
    reviewTextMode === "reading" && text?.content.reading_text != null
      ? [...highlightModel.byView.canonical_reading_text, ...manualHighlightViews.canonical]
      : [...highlightModel.byView.technical_raw_text, ...manualHighlightViews.raw];
  const highlightNavIds = [
    ...new Set(
      [...visibleHighlights]
        .sort((left, right) => left.start - right.start)
        .map((highlight) => highlight.primary_source_entity_id),
    ),
  ];
  const navigateHighlights = (direction: "prev" | "next") => {
    const length = highlightNavIds.length;
    if (length === 0) {
      return;
    }
    navPosition.current =
      navPosition.current === -1 && direction === "prev"
        ? length - 1
        : (navPosition.current + (direction === "next" ? 1 : -1) + length) % length;
    scrollAndFlash(`pii-mark-${highlightNavIds[navPosition.current]}`);
  };
  // Hide the recovered-job banner once a succeeded job's result has been applied (the loaded
  // content below speaks for itself); keep showing a failed/canceled job so the user always has a
  // controlled explanation, since that is the only user-view surface for a recovered failure.
  const trackedJobHandled = trackedOcrJob ? handledOcrJobIds.current.has(trackedOcrJob.job_id) : false;
  const showTrackedJobBanner =
    noLocalOcrRunInFlight &&
    trackedOcrJob !== null &&
    !(trackedOcrJob.status === "succeeded" && trackedJobHandled);
  // A full, current analysis exists once both OCR and PII match the latest upstream inputs.
  const hasCurrentAnalysis =
    ocrStatus === "current" && piiStatus === "current" && currentPiiEntityContract !== null;
  // Proactive hint when a station's runtime is not installed on this server (see
  // runtimeNotice.ts) — surfaces the same signal a run would otherwise only discover via a 503.
  const analysisRuntimeNotice = buildRuntimeNotice(appConfig);
  const ocrRuntimeNotice = buildStationRuntimeNotice(appConfig, "ocr");
  const piiRuntimeNotice = buildStationRuntimeNotice(appConfig, "pii");
  const devPiiSettingsEnabled = appConfig?.devEngineSettingsEnabled ?? false;
  // The dev view (and its toggle) exists only where dev engine settings are enabled; everywhere
  // else the user view is the sole, default experience.
  const effectiveViewMode: ViewMode = devGateEnabled ? viewMode : "user";
  const isDevView = effectiveViewMode === "dev";
  // Review interactions (decisions, jump targets) are only offered against a current PII result.
  // The dev view keeps its second column (entity list + group cards); the user view reviews
  // directly in the text via the decision popover, so it stays single-column.
  const reviewInteractive = piiStatus === "current";
  const showSecondColumn = isDevView;

  // Resolve the clicked highlight against the *current* review result: a manual addition decides
  // itself; an occurrence with an individual override decides that occurrence; everything else
  // decides its whole entity group (same value everywhere in the document).
  const decisionTarget: PiiDecisionTarget | null = (() => {
    if (!decisionAnchor || !reviewResult) {
      return null;
    }
    const addition = reviewResult.manual_additions.find(
      (candidate) => candidate.addition_id === decisionAnchor.entityId,
    );
    if (addition) {
      if (addition.artifact_currency === "stale") {
        return null;
      }
      return {
        scope: "manual_addition",
        targetId: addition.addition_id,
        entityType: addition.entity_type,
        occurrenceCount: 1,
        reviewStatus: addition.review_status,
        currentDecision: addition.review_decision ?? "pseudonymize",
      };
    }
    const occurrence = reviewResult.occurrences.find(
      (candidate) => candidate.occurrence_id === decisionAnchor.entityId,
    );
    if (!occurrence) {
      return null;
    }
    if (occurrence.decision_scope === "occurrence") {
      return {
        scope: "occurrence",
        targetId: occurrence.occurrence_id,
        entityType: occurrence.entity_type,
        occurrenceCount: 1,
        reviewStatus: occurrence.review_status,
        currentDecision: occurrence.review_decision ?? "pseudonymize",
      };
    }
    const group = reviewResult.groups.find(
      (candidate) => candidate.entity_group_id === occurrence.entity_group_id,
    );
    if (!group) {
      return null;
    }
    return {
      scope: "entity_group",
      targetId: group.entity_group_id,
      entityType: group.entity_type,
      occurrenceCount: group.occurrence_count,
      reviewStatus: group.review_status,
      currentDecision: group.review_decision ?? "pseudonymize",
    };
  })();

  // After an in-place decision: confirm quietly and offer a one-shot undo that re-submits the
  // decision that was in effect before (captured on the target at popover-open time).
  const handleDecided = (target: PiiDecisionTarget, decision: PiiReviewDecisionValue) => {
    const previousDecision = target.currentDecision;
    setToast({
      message: `Gespeichert: ${reviewDecisionLabel(decision)}`,
      undo: async () => {
        try {
          await submitPiiReviewDecision(documentId, {
            target_type: target.scope,
            target_id: target.targetId,
            decision: previousDecision,
          });
          const review = await fetchPiiReview(documentId);
          if (review) {
            await refreshPiiReviewAndContract(review);
          }
          setToast({ message: "Entscheidung wurde rückgängig gemacht." });
        } catch {
          setToast({ message: "Rückgängig machen ist fehlgeschlagen." });
        }
      },
    });
  };
  const piiRunRequest: PiiRunRequest | undefined =
    devPiiSettingsEnabled && selectedPiiProfile !== ""
      ? { pii_profile: selectedPiiProfile }
      : undefined;

  const execute = async <T,>(
    station: StationName,
    action: () => Promise<T>,
    apply: (result: T) => void,
  ) => {
    setPending((current) => ({ ...current, [station]: true }));
    setStationErrors((current) => ({ ...current, [station]: null }));
    try {
      apply(await action());
    } catch (error) {
      setStationErrors((current) => ({
        ...current,
        [station]: toStationError(error, station),
      }));
    } finally {
      setPending((current) => ({ ...current, [station]: false }));
    }
  };

  return (
    <div className="px-4 py-10 sm:px-6 sm:py-12">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link to="/documents" className="text-sm font-medium text-accent-dark hover:underline">
            ← Zurück zu Dokumenten
          </Link>
          {devGateEnabled && (
            <ViewModeToggle
              mode={viewMode}
              onChange={(mode) => {
                setViewMode(mode);
                setDecisionAnchor(null);
                if (mode === "user") setReviewTextMode("reading");
              }}
            />
          )}
        </div>

        <section className="mt-5 rounded-2xl border border-card-border bg-card p-6 shadow-[0_2px_12px_rgba(31,79,67,0.05)]">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">Dokument</p>
              <h1 className="mt-1 break-words text-2xl font-semibold text-ink">{document.filename}</h1>
              <p className="mt-2 text-sm text-muted">
                {formatTimestamp(document.uploaded_at)} · {formatBytes(document.size)}
              </p>
            </div>
            <span className="w-fit rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent-dark">
              {documentStatusLabel(document.status)}
            </span>
          </div>
          {isDevView && (
            <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
              <Metadata label="MIME-Type" value={document.detected_mime_type ?? "Legacy/Unbekannt"} />
              <Metadata label="Dokument-ID" value={document.id} code />
              <Metadata label="Original-Artifact" value={document.original_artifact?.id ?? "Nicht vorhanden"} code />
              <div className="sm:col-span-2 lg:col-span-3">
                <Metadata label="SHA-256" value={document.sha256 ?? "Legacy/Unbekannt"} code />
              </div>
            </dl>
          )}
        </section>

        {isDevView && (
        <div className="mt-6 grid gap-4 lg:grid-cols-3">
          <StationPanel
            title="Audit"
            status={auditStatus}
            actionLabel={audit ? "Audit erneut erstellen" : "Audit starten"}
            actionHint={audit ? RERUN_HINT : undefined}
            pendingLabel="Audit läuft …"
            pending={pending.audit}
            disabled={pending.audit || pending.ocr}
            error={stationErrors.audit}
            onAction={() => void execute("audit", () => runAudit(documentId), setAudit)}
          >
            {audit ? <AuditSummary artifact={audit} /> : <p>Original wurde noch nicht analysiert.</p>}
          </StationPanel>

          <StationPanel
            title="OCR / Text"
            status={ocrStatus}
            actionLabel={text ? "OCR erneut erstellen" : "OCR starten"}
            actionHint={text ? RERUN_HINT : undefined}
            pendingLabel="OCR läuft …"
            pending={pending.ocr}
            disabled={!audit || pending.audit || pending.ocr || pending.pii}
            disabledReason={!audit ? "Zuerst ein Audit erstellen." : undefined}
            runtimeNotice={ocrRuntimeNotice}
            error={stationErrors.ocr}
            onAction={() =>
              void execute("ocr", () => runOcr(documentId), (result) => {
                setText(result);
                setReviewTextMode("reading");
              })
            }
          >
            {text ? <TextSummary artifact={text} /> : <p>Noch kein Text-Artifact vorhanden.</p>}
          </StationPanel>

          <StationPanel
            title="PII"
            status={piiStatus}
            actionLabel={
              devPiiSettingsEnabled
                ? "PII mit ausgewähltem Profil starten"
                : pii
                  ? "PII erneut erstellen"
                  : "PII starten"
            }
            actionHint={devPiiSettingsEnabled ? DEV_PII_HINT : pii ? RERUN_HINT : undefined}
            pendingLabel="PII-Erkennung läuft …"
            pending={pending.pii}
            disabled={!text || pending.ocr || pending.pii}
            disabledReason={!text ? "Zuerst OCR/Text erzeugen." : undefined}
            runtimeNotice={piiRuntimeNotice}
            error={stationErrors.pii}
            onAction={() => void execute("pii", () => runPii(documentId, piiRunRequest), setPii)}
          >
            {pii ? <PiiSummary artifact={pii} /> : <p>PII-Erkennung noch nicht ausgeführt.</p>}
            <PiiEngineSettingsPanel
              config={appConfig?.pii ?? null}
              devSettingsEnabled={devPiiSettingsEnabled}
              selectedProfile={selectedPiiProfile}
              artifactSettings={pii?.content.engine_settings ?? null}
              onProfileChange={setSelectedPiiProfile}
            />
            {isDevView && pii && <PiiValidationTransparency validation={pii.content.validation} />}
          </StationPanel>
        </div>
        )}

        <section className="mt-6 rounded-2xl border border-card-border bg-card p-6 shadow-[0_2px_12px_rgba(31,79,67,0.05)]">
          <div className="mb-5">
            <h2 className="text-lg font-semibold text-ink">Review</h2>
            <p className="mt-1 text-sm text-muted">
              Extrahierter Text und erkannte PII-Entities. Es werden keine Inhalte verändert.
            </p>
          </div>
          {/* Reload-recovery status: reflects a background-tracked OCR job (e.g. after a page
              reload) while nothing on this page is already showing its own live progress UI. */}
          {showTrackedJobBanner && (
            <JobStatusBanner
              job={trackedOcrJob}
              pollFailureMessage={trackedOcrJobPollFailure}
            />
          )}
          {noLocalOcrRunInFlight && ocrResultLoadError && (
            <StatusNotice
              status="error"
              message="Die Texterkennung wurde abgeschlossen, das Ergebnis konnte aber nicht geladen werden. Bitte laden Sie die Seite neu."
            />
          )}
          {piiStatus === "current" && piiEntityContractState.status === "error" && (
            <StatusNotice
              status="error"
              message="Das genaue PII-Ergebnis konnte nicht geladen werden. Text und Hervorhebungen bleiben aus Sicherheitsgründen verborgen. Bitte laden Sie die Seite neu."
            />
          )}
          {piiStatus === "current" && piiEntityContractState.status === "incompatible" && (
            <StatusNotice
              status="error"
              message="PII- und Textergebnis gehören nicht zum selben Lauf. Text und Hervorhebungen bleiben verborgen."
            />
          )}
          {/* Warning, not error: earlier decisions were deliberately not reapplied to a new run —
              nothing is broken, the reader just has to look at those spots again. */}
          {piiStatus === "current" && reviewResult && reviewResult.has_stale_decisions && (
            <StatusNotice
              status="warning"
              message={`${reviewResult.stale_decision_count} frühere Überprüfungsentscheidung(en) beziehen sich auf einen vorherigen Analyse-Lauf und wurden nicht übernommen. Bitte prüfen Sie die betroffenen Stellen erneut.`}
            />
          )}
          {/* User view gets a single product-facing analysis action; dev view keeps its separate
              per-station controls above and never renders this panel. Once a current analysis
              exists there is nothing a re-run would change for the reader, so the action
              disappears instead of inviting a pointless (re-)run — it comes back by itself as
              soon as any upstream artifact makes the analysis stale. */}
          {!isDevView &&
            (ocrStatus !== "current" ||
              piiStatus !== "current" ||
              isAnalysisRunning(analysisStep) ||
              analysisError !== null) && (
            <div className="mb-5">
              <DocumentAnalysisPanel
                step={analysisStep}
                hasCurrentAnalysis={hasCurrentAnalysis}
                error={analysisError}
                runtimeNotice={analysisRuntimeNotice}
                onRun={() => void runUserAnalysis()}
              />
            </div>
          )}
          {!text ? (
            isDevView ? (
              <p className="rounded-lg bg-dropzone p-4 text-sm text-muted">
                OCR/Text noch nicht ausgeführt.
              </p>
            ) : (
              <p className="rounded-lg bg-dropzone p-4 text-sm text-muted">
                Dieses Dokument wurde noch nicht analysiert. Starten Sie die Analyse, um den
                extrahierten Text und erkannte sensible Daten zu sehen.
              </p>
            )
          ) : piiStatus === "current" && currentPiiEntityContract === null ? (
            <p className="rounded-lg bg-dropzone p-4 text-sm text-muted">
              Das genaue PII-Ergebnis ist nicht verfügbar. Text und Hervorhebungen werden nicht
              angezeigt.
            </p>
          ) : (
            <div
              className={
                showSecondColumn
                  ? "grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
                  : "grid gap-6"
              }
            >
              <div>
                {/* User view: the former sidebar collapses into one quiet summary line; every
                    decision happens directly on the highlight via the popover below. */}
                {!isDevView && reviewInteractive && reviewResult && (
                  <ReviewSummaryBar
                    review={reviewResult}
                    onNavigate={highlightNavIds.length > 0 ? navigateHighlights : undefined}
                  />
                )}
                <ReviewTextViewer
                  rawText={text.content.text}
                  readingText={text.content.reading_text}
                  layoutText={text.content.layout_text_result}
                  highlightModel={highlightModel}
                  mode={reviewTextMode}
                  onModeChange={(mode) => {
                    setReviewTextMode(mode);
                    // The visible mark set changes with the view; restart the jump cycle.
                    navPosition.current = -1;
                  }}
                  devMode={isDevView}
                  showEntityMeta={isDevView}
                  onSelectEntity={
                    !reviewInteractive
                      ? undefined
                      : isDevView
                        ? (entityId) => setSelectedOccurrenceId(entityId)
                        : (entityId, element) =>
                            setDecisionAnchor({
                              entityId,
                              rect: element.getBoundingClientRect(),
                            })
                  }
                  manualAdditions={reviewResult?.manual_additions ?? []}
                  onTextSelected={reviewInteractive ? setSelectedTextRange : undefined}
                />
                {reviewInteractive && text.content.reading_text && (
                  // Sticky at the viewport bottom: the paper is full page height now, so a
                  // selection made mid-document must not open a panel far below the fold.
                  <div className="sticky bottom-3 z-20">
                    <AddPiiManualEntity
                      documentId={documentId}
                      entityTypes={pii?.content.configured_entity_types ?? []}
                      readingText={text.content.reading_text}
                      selection={selectedTextRange}
                      onAdded={(review) => {
                        setSelectedTextRange(null);
                        void refreshPiiReviewAndContract(review);
                      }}
                    />
                  </div>
                )}
                {isDevView && !pii && (
                  <p className="mt-3 text-xs text-muted">PII-Erkennung noch nicht ausgeführt.</p>
                )}
              </div>
              {isDevView &&
                (pii ? (
                  // The document column scrolls with the page; the technical sidebar pins to the
                  // viewport and keeps its own scroll so it stays usable beside a long paper.
                  <div className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-auto">
                    <PiiEntityList
                      entities={pii.content.entities}
                      stale={piiStatus === "stale"}
                      documentId={documentId}
                      artifactId={pii.id}
                      feedbackEnabled={devPiiSettingsEnabled}
                      feedbackStatuses={feedbackStatuses}
                      review={reviewResult}
                      onReviewChanged={(review) => void refreshPiiReviewAndContract(review)}
                      selectedOccurrenceId={selectedOccurrenceId}
                    />
                    {reviewInteractive && (
                      <PiiReviewGroupList
                        documentId={documentId}
                        review={reviewResult}
                        onReviewChanged={(review) => void refreshPiiReviewAndContract(review)}
                        showTechnicalDetails
                        showDetectedGroups={false}
                      />
                    )}
                  </div>
                ) : (
                  <section>
                    <h2 className="font-semibold text-ink">Erkannte Entities</h2>
                    <p className="mt-4 text-sm text-muted">PII-Erkennung noch nicht ausgeführt.</p>
                  </section>
                ))}
            </div>
          )}
        </section>

        {!isDevView && decisionAnchor && decisionTarget && (
          <PiiDecisionPopover
            documentId={documentId}
            target={decisionTarget}
            anchorRect={decisionAnchor.rect}
            onClose={() => setDecisionAnchor(null)}
            onReviewChanged={(review) => void refreshPiiReviewAndContract(review)}
            onDecided={handleDecided}
          />
        )}

        {toast && (
          <Toast
            message={toast.message}
            actionLabel={toast.undo ? "Rückgängig" : undefined}
            onAction={
              toast.undo
                ? () => {
                    const undo = toast.undo;
                    setToast(null);
                    void undo?.();
                  }
                : undefined
            }
            onClose={() => setToast(null)}
          />
        )}

      </div>
    </div>
  );
}

/** The backend status is a technical enum ("received"); the chip shows plain German, with the raw
 *  value as fallback so an unknown future status is never hidden. */
function documentStatusLabel(status: string): string {
  return status === "received" ? "Hochgeladen" : status;
}

function Metadata({ label, value, code = false }: { label: string; value: string; code?: boolean }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`mt-1 break-all text-ink ${code ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}

function AuditSummary({ artifact }: { artifact: AuditArtifact }) {
  const { content } = artifact;
  return (
    <dl className="space-y-1">
      <SummaryRow label="Typ" value={content.document_kind.toUpperCase()} />
      {content.page_count !== null && <SummaryRow label="Seiten" value={String(content.page_count)} />}
      <SummaryRow label="Textzeichen" value={String(content.text_char_count)} />
      <SummaryRow label="Textlayer" value={content.has_text_layer ? "Vorhanden" : "Nicht vorhanden"} />
    </dl>
  );
}

function TextSummary({ artifact }: { artifact: TextArtifact }) {
  return (
    <dl className="space-y-1">
      <SummaryRow label="Quelle" value={artifact.content.source} />
      <SummaryRow label="Rohtext-Zeichen" value={String(artifact.content.text_char_count)} />
      <SummaryRow label="Seiten" value={String(artifact.content.pages.length)} />
    </dl>
  );
}

function PiiSummary({ artifact }: { artifact: PiiArtifact }) {
  const profile = artifact.content.engine_settings?.pii_profile ?? artifact.content.profile;
  return (
    <dl className="space-y-1">
      <SummaryRow label="Entities" value={String(artifact.content.entities.length)} />
      <SummaryRow label="Sprache" value={artifact.content.language} />
      <SummaryRow label="Profil" value={profile} />
      <SummaryRow label="Schwellwert" value={artifact.content.score_threshold.toFixed(2)} />
    </dl>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt>{label}</dt>
      <dd className="break-all text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

async function loadOptional<T>(
  load: () => Promise<T>,
  station: StationName,
): Promise<{ data: T | null; error: UiError | null }> {
  try {
    return { data: await load(), error: null };
  } catch (error) {
    if (error instanceof WorkstationApiError && error.status === 404) {
      return { data: null, error: null };
    }
    return { data: null, error: toStationError(error, station) };
  }
}

function toDocumentError(error: unknown): UiError {
  if (error instanceof DocumentsApiError) {
    return {
      message: error.status === 404 ? "Dokument nicht gefunden." : error.message,
      correlationId: error.correlationId,
    };
  }
  return { message: "Dokument konnte nicht geladen werden.", correlationId: null };
}
