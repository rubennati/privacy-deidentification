export type ViewMode = "user" | "dev";

interface ViewModeToggleProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
}

const BUTTON_BASE = "rounded-md px-3 py-1.5 text-xs font-medium transition-colors";

/**
 * Small pill switch between the reduced user view and the full technical dev view. Rendered only
 * when dev engine settings are enabled; it changes presentation only and never runs any station.
 */
export function ViewModeToggle({ mode, onChange }: ViewModeToggleProps) {
  return (
    <div
      className="flex rounded-lg border border-card-border bg-dropzone p-1"
      role="group"
      aria-label="Ansicht"
    >
      <button
        type="button"
        onClick={() => onChange("user")}
        aria-pressed={mode === "user"}
        className={`${BUTTON_BASE} ${
          mode === "user" ? "bg-card text-ink shadow-sm" : "text-muted hover:text-ink"
        }`}
      >
        User view
      </button>
      <button
        type="button"
        onClick={() => onChange("dev")}
        aria-pressed={mode === "dev"}
        className={`${BUTTON_BASE} ${
          mode === "dev" ? "bg-card text-ink shadow-sm" : "text-muted hover:text-ink"
        }`}
      >
        Dev view
      </button>
    </div>
  );
}
