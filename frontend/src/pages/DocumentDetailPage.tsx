import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchAppConfig, type AppConfig } from "../api/config";
import { DocumentsApiError, fetchDocument, type DocumentSummary } from "../api/documents";
import {
  fetchAudit,
  fetchOcr,
  fetchPii,
  runAudit,
  runOcr,
  runPii,
  type AuditArtifact,
  type PiiArtifact,
  type PiiRunRequest,
  type TextArtifact,
  WorkstationApiError,
} from "../api/workstations";
import {
  buildFeedbackStatusMap,
  fetchPiiFeedbackSummary,
  type PiiFeedbackStatus,
} from "../api/piiFeedback";
import { PiiEntityList } from "../components/pii/PiiEntityList";
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
import { formatBytes, formatTimestamp } from "../lib/format";

interface UiError {
  message: string;
  correlationId: string | null;
}

type StationName = "audit" | "ocr" | "pii";

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
  const [reviewTextMode, setReviewTextMode] = useState<ReviewTextMode>("canonical");
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
    setReviewTextMode("canonical");

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
  const currentPiiEntities = piiStatus === "current" ? (pii?.content.entities ?? []) : [];
  const devPiiSettingsEnabled = appConfig?.devEngineSettingsEnabled ?? false;
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
    <main className="min-h-screen bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)] px-4 py-10 sm:py-14">
      <div className="mx-auto max-w-6xl">
        <Link to="/documents" className="text-sm font-medium text-accent-dark hover:underline">
          ← Zurück zu Dokumenten
        </Link>

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
          <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <Metadata label="MIME-Type" value={document.detected_mime_type ?? "Legacy/Unbekannt"} />
            <Metadata label="Dokument-ID" value={document.id} code />
            <Metadata label="Original-Artifact" value={document.original_artifact?.id ?? "Nicht vorhanden"} code />
            <div className="sm:col-span-2 lg:col-span-3">
              <Metadata label="SHA-256" value={document.sha256 ?? "Legacy/Unbekannt"} code />
            </div>
          </dl>
        </section>

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
            error={stationErrors.ocr}
            onAction={() =>
              void execute("ocr", () => runOcr(documentId), (result) => {
                setText(result);
                setReviewTextMode("canonical");
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

        <section className="mt-6 rounded-2xl border border-card-border bg-card p-6 shadow-[0_2px_12px_rgba(31,79,67,0.05)]">
          <div className="mb-5">
            <h2 className="text-lg font-semibold text-ink">Review</h2>
            <p className="mt-1 text-sm text-muted">
              Extrahierter Text und erkannte PII-Entities. Es werden keine Inhalte verändert.
            </p>
          </div>
          {!text ? (
            <p className="rounded-lg bg-dropzone p-4 text-sm text-muted">
              OCR/Text noch nicht ausgeführt.
            </p>
          ) : (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
              <div>
                <ReviewTextViewer
                  canonicalText={text.content.text}
                  layoutText={text.content.layout_text_result}
                  entities={currentPiiEntities}
                  mode={reviewTextMode}
                  onModeChange={setReviewTextMode}
                />
                {!pii && (
                  <p className="mt-3 text-xs text-muted">PII-Erkennung noch nicht ausgeführt.</p>
                )}
              </div>
              {pii ? (
                <PiiEntityList
                  entities={pii.content.entities}
                  stale={piiStatus === "stale"}
                  documentId={documentId}
                  artifactId={pii.id}
                  feedbackEnabled={devPiiSettingsEnabled}
                  feedbackStatuses={feedbackStatuses}
                />
              ) : (
                <section>
                  <h2 className="font-semibold text-ink">Erkannte Entities</h2>
                  <p className="mt-4 text-sm text-muted">PII-Erkennung noch nicht ausgeführt.</p>
                </section>
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
      <SummaryRow label="Zeichen" value={String(artifact.content.text_char_count)} />
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

function toStationError(error: unknown, station: StationName): UiError {
  if (!(error instanceof WorkstationApiError)) {
    return { message: "Ein unerwarteter Fehler ist aufgetreten.", correlationId: null };
  }
  const message =
    error.status === 0
      ? "Keine Verbindung zum Server."
      : error.status === 409
        ? station === "ocr"
          ? "Zuerst ein gültiges Audit erstellen."
          : station === "pii"
            ? "Zuerst OCR/Text erzeugen."
            : "Das Original-Artifact ist nicht verwendbar."
        : error.status === 403
          ? "Dev Engine Settings sind auf diesem Server deaktiviert."
        : error.status === 422
          ? station === "pii"
            ? "Der Text konnte nicht verarbeitet werden."
            : "Das Dokument konnte nicht verarbeitet werden."
          : error.status === 503
            ? "Die benötigte Runtime oder das Modell ist nicht verfügbar."
            : error.message;
  return { message, correlationId: error.correlationId };
}
