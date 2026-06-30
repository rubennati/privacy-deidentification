import { useCallback, useEffect, useState } from "react";

import { deleteDocument, DocumentsApiError, fetchDocuments } from "../api/documents";
import type { DocumentSummary } from "../api/documents";
import { DocumentCard } from "../components/documents/DocumentCard";
import { EmptyState } from "../components/documents/EmptyState";
import { StatusNotice, type UploadStatus } from "../components/StatusNotice";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ status: UploadStatus; message: string }>({
    status: "idle",
    message: "",
  });

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await fetchDocuments());
    } catch (error) {
      setNotice({
        status: "error",
        message:
          error instanceof DocumentsApiError
            ? error.message
            : "Dokumente konnten nicht geladen werden.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const handleDelete = useCallback(
    async (id: string) => {
      setPendingDeleteId(id);
      try {
        await deleteDocument(id);
        setNotice({ status: "success", message: "Dokument wurde gelöscht." });
        await loadDocuments();
      } catch (error) {
        setNotice({
          status: "error",
          message:
            error instanceof DocumentsApiError
              ? error.message
              : "Dokument konnte nicht gelöscht werden.",
        });
      } finally {
        setPendingDeleteId(null);
      }
    },
    [loadDocuments],
  );

  return (
    <main className="flex min-h-screen justify-center bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)] p-4 py-12 sm:py-16">
      <div className="h-fit w-full max-w-2xl rounded-2xl border border-card-border bg-card p-8 shadow-[0_2px_12px_rgba(31,79,67,0.05)] sm:p-10">
        <header className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Dokumente</h1>
          <p className="mt-2 text-sm text-muted">
            Hier sehen Sie die Dateien, die für den nächsten Verarbeitungsschritt bereitstehen.
          </p>
        </header>

        <StatusNotice status={notice.status} message={notice.message} />

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
                onDelete={(id) => void handleDelete(id)}
                deleting={pendingDeleteId === document.id}
              />
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
