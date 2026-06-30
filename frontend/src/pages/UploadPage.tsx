import { useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { uploadDocument, UploadError } from "../api/uploads";
import { HowItWorks } from "../components/HowItWorks";
import { StatusNotice, type UploadStatus } from "../components/StatusNotice";
import { UploadDropzone } from "../components/UploadDropzone";
import { validateFile } from "../lib/fileValidation";

export default function UploadPage() {
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [message, setMessage] = useState("");

  const handleFile = useCallback(async (file: File) => {
    const validationError = validateFile(file);
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
      setMessage(`„${accepted.filename}“ — Dokument wurde entgegengenommen.`);
    } catch (error) {
      setStatus("error");
      setMessage(
        error instanceof UploadError
          ? error.message
          : "Ein unerwarteter Fehler ist aufgetreten.",
      );
    }
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)] p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-card-border bg-card p-8 shadow-[0_2px_12px_rgba(31,79,67,0.05)] sm:p-10">
        <header className="mb-6">
          <h1 className="text-xl font-semibold text-ink">Dokumente sicher vorbereiten</h1>
          <p className="mt-2 text-sm text-muted">
            Laden Sie Dateien hoch, um sensible Inhalte für Review, De-Identification und sichere
            Weiterverarbeitung vorzubereiten.
          </p>
        </header>

        <UploadDropzone onFile={(file) => void handleFile(file)} disabled={status === "uploading"} />
        <StatusNotice status={status} message={message} />
        {status === "success" && (
          <p className="mt-3 text-center text-sm">
            <Link to="/documents" className="font-medium text-accent-dark hover:underline">
              Zu den Dokumenten →
            </Link>
          </p>
        )}
        <HowItWorks />
      </div>
    </main>
  );
}
