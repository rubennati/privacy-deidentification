import { useCallback, useState } from "react";

import { uploadDocument, UploadError } from "./api/uploads";
import { HowItWorks } from "./components/HowItWorks";
import { StatusNotice, type UploadStatus } from "./components/StatusNotice";
import { UploadDropzone } from "./components/UploadDropzone";
import { validateFile } from "./lib/fileValidation";

export default function App() {
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
      setMessage(`„${accepted.filename}“ wurde hochgeladen und wird verarbeitet.`);
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
    <main className="flex min-h-screen items-center justify-center bg-[#e8ece4] p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-black/5 bg-white p-8 shadow-sm sm:p-10">
        <header className="mb-6">
          <h1 className="text-lg font-semibold text-gray-900">Dokument hochladen</h1>
          <p className="mt-1 text-sm text-gray-500">
            Laden Sie ein Dokument hoch. Nur Dateien mit Textinhalt können hochgeladen werden.
          </p>
        </header>

        <UploadDropzone onFile={(file) => void handleFile(file)} disabled={status === "uploading"} />
        <StatusNotice status={status} message={message} />
        <HowItWorks />
      </div>
    </main>
  );
}
