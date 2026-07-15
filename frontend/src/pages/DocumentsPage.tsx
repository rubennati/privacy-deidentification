import { useState } from "react";
import { Link } from "react-router-dom";

import { DocumentsApiError } from "../api/documents";
import { DocumentCard } from "../components/documents/DocumentCard";
import { EmptyState } from "../components/documents/EmptyState";
import { StatusNotice, type UploadStatus } from "../components/StatusNotice";
import {
  useDeleteDocument,
  useDocumentAnalysisStates,
  useDocuments,
} from "../hooks/useDocuments";

interface Notice {
  status: UploadStatus;
  message: string;
  correlationId: string | null;
}

function errorNotice(error: unknown, fallback: string): Notice {
  return {
    status: "error",
    message: error instanceof DocumentsApiError ? error.message : fallback,
    correlationId: error instanceof DocumentsApiError ? error.correlationId : null,
  };
}

export default function DocumentsPage() {
  const documentsQuery = useDocuments();
  const documents = documentsQuery.data ?? [];
  const analysisById = useDocumentAnalysisStates(documents);
  const deleteMutation = useDeleteDocument();
  // Transient toast for a delete outcome; the list/loading/error come from the query itself.
  const [deleteNotice, setDeleteNotice] = useState<Notice>({
    status: "idle",
    message: "",
    correlationId: null,
  });

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id, {
      onSuccess: () =>
        setDeleteNotice({ status: "success", message: "Dokument wurde gelöscht.", correlationId: null }),
      onError: (error) => setDeleteNotice(errorNotice(error, "Dokument konnte nicht gelöscht werden.")),
    });
  };

  const notice: Notice = documentsQuery.isError
    ? errorNotice(documentsQuery.error, "Dokumente konnten nicht geladen werden.")
    : deleteNotice;

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

      {documentsQuery.isPending && (
        <p className="mt-6 text-sm text-muted">Dokumente werden geladen …</p>
      )}

      {documentsQuery.isSuccess && documents.length === 0 && <EmptyState />}

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
              onDelete={(id) => handleDelete(id)}
              deleting={deleteMutation.isPending && deleteMutation.variables === document.id}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
