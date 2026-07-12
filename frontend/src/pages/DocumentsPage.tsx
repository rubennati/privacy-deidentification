import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { deleteDocument, DocumentsApiError, fetchDocuments } from "../api/documents";
import type { DocumentSummary } from "../api/documents";
import { fetchDocumentJobs } from "../api/workstations";
import { DocumentCard } from "../components/documents/DocumentCard";
import { EmptyState } from "../components/documents/EmptyState";
import { StatusNotice, type UploadStatus } from "../components/StatusNotice";
import { deriveAnalysisState, type DocumentAnalysisState } from "../lib/documentListStatus";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  // Metadata-only analysis state per document id; a document missing here stays without a badge
  // (its jobs request failed) instead of guessing.
  const [analysisById, setAnalysisById] = useState<Record<string, DocumentAnalysisState>>({});
  const [notice, setNotice] = useState<{
    status: UploadStatus;
    message: string;
    correlationId: string | null;
  }>({ status: "idle", message: "", correlationId: null });

  const loadAnalysisStates = useCallback(async (docs: readonly DocumentSummary[]) => {
    const entries = await Promise.all(
      docs.map(async (document) => {
        try {
          return [document.id, deriveAnalysisState(await fetchDocumentJobs(document.id))] as const;
        } catch {
          return null;
        }
      }),
    );
    setAnalysisById(
      Object.fromEntries(entries.filter((entry): entry is NonNullable<typeof entry> => entry !== null)),
    );
  }, []);

  const loadDocuments = useCallback(async () => {
    try {
      const loaded = await fetchDocuments();
      setDocuments(loaded);
      void loadAnalysisStates(loaded);
    } catch (error) {
      setNotice({
        status: "error",
        message:
          error instanceof DocumentsApiError
            ? error.message
            : "Dokumente konnten nicht geladen werden.",
        correlationId: error instanceof DocumentsApiError ? error.correlationId : null,
      });
    } finally {
      setLoading(false);
    }
  }, [loadAnalysisStates]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // While any document is being analyzed, refresh the badges on a slow poll so "Analyse läuft"
  // resolves without a manual reload. No polling once everything is settled.
  useEffect(() => {
    if (!Object.values(analysisById).includes("running")) {
      return;
    }
    const timer = setTimeout(() => {
      void loadAnalysisStates(documents);
    }, 8000);
    return () => clearTimeout(timer);
  }, [analysisById, documents, loadAnalysisStates]);

  const handleDelete = useCallback(
    async (id: string) => {
      setPendingDeleteId(id);
      try {
        await deleteDocument(id);
        setNotice({ status: "success", message: "Dokument wurde gelöscht.", correlationId: null });
        await loadDocuments();
      } catch (error) {
        setNotice({
          status: "error",
          message:
            error instanceof DocumentsApiError
              ? error.message
              : "Dokument konnte nicht gelöscht werden.",
          correlationId: error instanceof DocumentsApiError ? error.correlationId : null,
        });
      } finally {
        setPendingDeleteId(null);
      }
    },
    [loadDocuments],
  );

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 sm:py-12">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-md">
          <h1 className="text-2xl font-semibold text-ink">Dokumente</h1>
          <p className="mt-2 text-sm text-muted">
            Hier sehen Sie die Dateien, die für den nächsten Verarbeitungsschritt bereitstehen.
          </p>
        </div>
        <Link
          to="/upload"
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          Dokument hochladen
        </Link>
      </header>

      <StatusNotice
        status={notice.status}
        message={notice.message}
        correlationId={notice.correlationId}
      />

      {loading && documents.length === 0 && (
        <p className="mt-6 text-sm text-muted">Dokumente werden geladen …</p>
      )}

      {!loading && documents.length === 0 && <EmptyState />}

      {documents.length > 0 && (
        <ul className="mt-6 flex flex-col gap-3">
          {documents.map((document) => (
            <DocumentCard
              key={document.id}
              id={document.id}
              filename={document.filename}
              size={document.size}
              uploadedAt={document.uploaded_at}
              analysis={analysisById[document.id]}
              onDelete={(id) => void handleDelete(id)}
              deleting={pendingDeleteId === document.id}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
