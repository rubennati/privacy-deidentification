import { useCallback, useEffect, useRef, useState } from "react";

import { ACCEPT_ATTRIBUTE } from "../lib/fileValidation";

interface UploadDropzoneProps {
  onFile: (file: File) => void;
  disabled?: boolean;
}

/**
 * The upload area from Screenshot 1: click to choose a file, drag & drop, or paste (Ctrl+V).
 * Rendered as a button so it is fully keyboard-operable.
 */
export function UploadDropzone({ onFile, disabled = false }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null | undefined) => {
      if (disabled || !files || files.length === 0) {
        return;
      }
      onFile(files[0]);
    },
    [disabled, onFile],
  );

  // Ctrl+V anywhere on the page inserts a file, as the tip promises.
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => handleFiles(event.clipboardData?.files);
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [handleFiles]);

  const openFilePicker = () => {
    if (!disabled) {
      inputRef.current?.click();
    }
  };

  return (
    <button
      type="button"
      onClick={openFilePicker}
      disabled={disabled}
      aria-label="Datei auswählen oder hierher ziehen"
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        handleFiles(event.dataTransfer.files);
      }}
      className={[
        "flex w-full flex-col items-center justify-center gap-3 rounded-xl px-6 py-12",
        "border-2 border-dashed text-center transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/40",
        isDragging ? "border-gray-400 bg-gray-100" : "border-transparent bg-gray-50",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-gray-100",
      ].join(" ")}
    >
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-gray-900 text-white">
        <UploadIcon />
      </span>
      <span className="text-base text-gray-500">Klicken Sie hier um eine Datei auszuwählen</span>
      <span className="text-sm text-gray-400">Unterstützt: PDF, DOCX, PNG, JPG</span>
      <span className="text-sm text-gray-400">oder ziehen Sie eine Datei hierher</span>
      <span className="text-xs text-gray-400">
        Tipp: Sie können auch Strg+V drücken, um eine Datei einzufügen
      </span>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        className="sr-only"
        onChange={(event) => {
          handleFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </button>
  );
}

function UploadIcon() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" x2="12" y1="3" y2="15" />
    </svg>
  );
}
