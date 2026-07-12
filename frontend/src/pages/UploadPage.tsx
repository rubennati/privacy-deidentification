import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchUploadConfig } from "../api/config";
import { uploadDocument, UploadError } from "../api/uploads";
import { HowItWorks } from "../components/HowItWorks";
import { StatusNotice, type UploadStatus } from "../components/StatusNotice";
import { UploadDropzone } from "../components/UploadDropzone";
import {
  buildAcceptAttribute,
  DEFAULT_CONSTRAINTS,
  type UploadConstraints,
  validateFile,
} from "../lib/fileValidation";

export default function UploadPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [message, setMessage] = useState("");
  const [correlationId, setCorrelationId] = useState<string | null>(null);
  const [constraints, setConstraints] = useState<UploadConstraints>(DEFAULT_CONSTRAINTS);

  // Mirror the backend's effective upload constraints (single source of truth).
  useEffect(() => {
    let active = true;
    void fetchUploadConfig().then((config) => {
      if (active && config) {
        setConstraints({
          allowedExtensions: config.allowedExtensions,
          maxUploadBytes: config.maxUploadBytes,
        });
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const handleFile = useCallback(
    async (file: File) => {
      setCorrelationId(null);

      const validationError = validateFile(file, constraints);
      if (validationError) {
        setStatus("error");
        setMessage(validationError.message);
        return;
      }

      setStatus("uploading");
      setMessage(`„${file.name}“ wird hochgeladen …`);

      try {
        const accepted = await uploadDocument(file);
        setStatus("success");
        setMessage(`„${accepted.filename}“ — Analyse wird gestartet …`);
        // Straight to the document with the analysis auto-started: the upload page promises
        // "Inhalte werden extrahiert und analysiert", so nobody should have to find and press a
        // second button for that. Router state (not a query param) so a copied link or a reload
        // of the detail page never re-triggers a run.
        navigate(`/documents/${encodeURIComponent(accepted.id)}`, {
          state: { autoAnalyze: true },
        });
      } catch (error) {
        setStatus("error");
        if (error instanceof UploadError) {
          setMessage(error.message);
          setCorrelationId(error.correlationId);
        } else {
          setMessage("Ein unerwarteter Fehler ist aufgetreten.");
        }
      }
    },
    [constraints, navigate],
  );

  return (
    <main className="flex min-h-screen justify-center bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)] p-4 py-12 sm:py-16">
      <div className="h-fit w-full max-w-2xl rounded-2xl border border-card-border bg-card p-8 shadow-[0_2px_12px_rgba(31,79,67,0.05)] sm:p-10">
        <header className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Dokumente sicher vorbereiten</h1>
          <p className="mt-2 text-sm text-muted">
            Laden Sie Dateien hoch, um sensible Inhalte für Review, De-Identification und sichere
            Weiterverarbeitung vorzubereiten.
          </p>
        </header>

        <UploadDropzone
          onFile={(file) => void handleFile(file)}
          disabled={status === "uploading"}
          accept={buildAcceptAttribute(constraints.allowedExtensions)}
        />
        <StatusNotice status={status} message={message} correlationId={correlationId} />
        <HowItWorks />
      </div>
    </main>
  );
}
