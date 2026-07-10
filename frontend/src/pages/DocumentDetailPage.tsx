import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

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
  type PiiReviewResult,
} from "../api/piiReview";
import {
  fetchPiiEntityContract,
  type PiiEntityContractV1,
} from "../api/piiEntityContract";
import { PiiEntityList } from "../components/pii/PiiEntityList";
import { PiiReviewGroupList } from "../components/pii/PiiReviewGroupList";
import { PiiEngineSettingsPanel } from "../components/pii/PiiEngineSettingsPanel";
import {
  ReviewTextViewer,
  type ReviewTextMode,
} from "../components/pii/ReviewTextViewer";
import {
  StationPanel,
  type StationStatus,
} from "../components/workstations/StationPanel";
import { StatusNotice } from "../components/StatusNotice";
import { DocumentAnalysisPanel } from "../components/DocumentAnalysisPanel";
import { ViewModeToggle, type ViewMode } from "../components/ViewModeToggle";
import {
  isAnalysisRunning,
  runDocumentAnalysis,
  type AnalysisStep,
} from "../lib/documentAnalysis";
import { toStationError, type StationName } from "../lib/stationErrors";
import { buildRuntimeNotice, buildStationRuntimeNotice } from "../lib/runtimeNotice";
import { buildAnchorBoundPiiHighlights } from "../lib/piiHighlights";
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
  "Ein neuer Lauf erzeugt ein neues Ergebnis. Ein gewaehltes Dev-Profil gilt nur fuer diesen Lauf.";

export default function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const [document, setDocument] = useState<DocumentSummary | null>(null);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [audit, setAudit] = useState<AuditArtifact | null>(null);
  const [text, setText] = useState<TextArtifact | null>(null);
  const [pii, setPii] = useState<PiiArtifact | null>(null);
  const [feedbackStatuses, setFeedbackStatuses] = useState<Record<string, PiiFeedbackStatus>>({});
  const [reviewResult, setReviewResult] = useState<PiiReviewResult | null>(null);
  const [piiEntityContract, setPiiEntityContract] = useState<PiiEntityContractV1 | null>(null);
  const [piiEntityContractError, setPiiEntityContractError] = useState(false);
  const [selectedOccurrenceId, setSelectedOccurrenceId] = useState<string | null>(null);
  const [reviewTextMode, setReviewTextMode] = useState<ReviewTextMode>("reading");
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
    setReviewTextMode("reading");
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
      setPiiEntityContract(null);
      setPiiEntityContractError(false);
      return;
    }
    let active = true;
    void Promise.all([fetchPiiReview(documentId), fetchPiiEntityContract(documentId)]).then(
      ([review, contractResult]) => {
        if (!active) return;
        setReviewResult(review);
        setPiiEntityContract(contractResult.status === "ok" ? contractResult.contract : null);
        setPiiEntityContractError(contractResult.status === "error");
      },
    );
    return () => {
      active = false;
    };
  }, [documentId, piiArtifactId]);

  const refreshPiiReviewAndContract = async (review: PiiReviewResult) => {
    setReviewResult(review);
    if (!documentId || !piiArtifactId) {
      setPiiEntityContract(null);
      setPiiEntityContractError(false);
      return;
    }
    const contractResult = await fetchPiiEntityContract(documentId);
    setPiiEntityContract(contractResult.status === "ok" ? contractResult.contract : null);
    setPiiEntityContractError(contractResult.status === "error");
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
      void fetchOcr(documentId)
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

  if (loading) {
    return (
      <main className="min-h-screen bg-page px-4 py-12">
        <p className="mx-auto max-w-6xl text-sm text-muted">Dokument wird geladen …</p>
      </main>
    );
  }

  if (!document || !documentId) {
    return (
      <main className="min-h-screen bg-page px-4 py-12">
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
      </main>
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
    piiStatus === "current" && piiEntityContract?.pii_artifact_id === piiArtifactId
      ? piiEntityContract
      : null;
  const highlightModel = buildAnchorBoundPiiHighlights(currentPiiEntityContract);
  // Hide the recovered-job banner once a succeeded job's result has been applied (the loaded
  // content below speaks for itself); keep showing a failed/canceled job so the user always has a
  // controlled explanation, since that is the only user-view surface for a recovered failure.
  const trackedJobHandled = trackedOcrJob ? handledOcrJobIds.current.has(trackedOcrJob.job_id) : false;
  const showTrackedJobBanner =
    noLocalOcrRunInFlight &&
    trackedOcrJob !== null &&
    !(trackedOcrJob.status === "succeeded" && trackedJobHandled);
  // A full, current analysis exists once both OCR and PII match the latest upstream inputs.
  const hasCurrentAnalysis = ocrStatus === "current" && piiStatus === "current";
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
  // The review-decision panel is not dev-gated on the backend, so it shows in both views once
  // there is something current to review; only the per-station Dev View entity list stays dev-only.
  const showReviewColumn = piiStatus === "current";
  const showSecondColumn = isDevView || showReviewColumn;
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

  return (
    <main className="min-h-screen bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)] px-4 py-10 sm:py-14">
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
              {document.status}
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
                ? "PII mit ausgewaehltem Profil starten"
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
          {showTrackedJobBanner && <JobStatusBanner job={trackedOcrJob} />}
          {noLocalOcrRunInFlight && ocrResultLoadError && (
            <StatusNotice
              status="error"
              message="Die Texterkennung wurde abgeschlossen, das Ergebnis konnte aber nicht geladen werden. Bitte laden Sie die Seite neu."
            />
          )}
          {piiStatus === "current" && piiEntityContractError && (
            <StatusNotice
              status="error"
              message="Die PII-Hervorhebungen konnten nicht geladen werden. Der erkannte Text ist weiterhin sichtbar, aber ohne Markierungen. Bitte laden Sie die Seite neu."
            />
          )}
          {piiStatus === "current" && reviewResult && reviewResult.has_stale_decisions && (
            <StatusNotice
              status="error"
              message={`Es liegen ${reviewResult.stale_decision_count} Überprüfungsentscheidung(en) aus einem vorherigen PII-Lauf vor, die für das aktuelle Ergebnis nicht mehr gelten. Bitte prüfen Sie die betroffenen Einträge erneut.`}
            />
          )}
          {/* User view gets a single product-facing analysis action; dev view keeps its separate
              per-station controls above and never renders this panel. */}
          {!isDevView && (
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
          ) : (
            <div
              className={
                showSecondColumn
                  ? "grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
                  : "grid gap-6"
              }
            >
              <div>
                <ReviewTextViewer
                  rawText={text.content.text}
                  readingText={text.content.reading_text}
                  layoutText={text.content.layout_text_result}
                  highlightModel={highlightModel}
                  mode={reviewTextMode}
                  onModeChange={setReviewTextMode}
                  devMode={isDevView}
                  showEntityMeta={isDevView}
                  onSelectEntity={showReviewColumn ? setSelectedOccurrenceId : undefined}
                />
                {isDevView && !pii && (
                  <p className="mt-3 text-xs text-muted">PII-Erkennung noch nicht ausgeführt.</p>
                )}
              </div>
              {isDevView ? (
                pii ? (
                  <div className="max-h-[70vh] overflow-auto">
                    <PiiEntityList
                      entities={pii.content.entities}
                      stale={piiStatus === "stale"}
                      documentId={documentId}
                      artifactId={pii.id}
                      feedbackEnabled={devPiiSettingsEnabled}
                      feedbackStatuses={feedbackStatuses}
                    />
                    {showReviewColumn && (
                      <PiiReviewGroupList
                        documentId={documentId}
                        review={reviewResult}
                        onReviewChanged={(review) => void refreshPiiReviewAndContract(review)}
                        selectedOccurrenceId={selectedOccurrenceId}
                        showTechnicalDetails
                      />
                    )}
                  </div>
                ) : (
                  <section>
                    <h2 className="font-semibold text-ink">Erkannte Entities</h2>
                    <p className="mt-4 text-sm text-muted">PII-Erkennung noch nicht ausgeführt.</p>
                  </section>
                )
              ) : (
                showReviewColumn && (
                  <div className="max-h-[70vh] overflow-auto">
                    <PiiReviewGroupList
                      documentId={documentId}
                      review={reviewResult}
                      onReviewChanged={(review) => void refreshPiiReviewAndContract(review)}
                      selectedOccurrenceId={selectedOccurrenceId}
                      showTechnicalDetails={false}
                    />
                  </div>
                )
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
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
