import type { ChangeEvent } from "react";

import type { PiiRuntimeConfig } from "../../api/config";
import type { PiiArtifactEngineSettings } from "../../api/workstations";

interface PiiEngineSettingsPanelProps {
  config: PiiRuntimeConfig | null;
  devSettingsEnabled: boolean;
  selectedProfile: string;
  artifactSettings: PiiArtifactEngineSettings | null;
  onProfileChange: (profile: string) => void;
}

export function PiiEngineSettingsPanel({
  config,
  devSettingsEnabled,
  selectedProfile,
  artifactSettings,
  onProfileChange,
}: PiiEngineSettingsPanelProps) {
  const profileOptions = config ? buildProfileOptions(config) : [];
  if (!artifactSettings && !(devSettingsEnabled && config)) {
    return null;
  }
  return (
    <div className="mt-4 space-y-3 rounded-xl border border-card-border bg-dropzone p-4">
      {artifactSettings ? (
        <section aria-labelledby="artifact-engine-settings-heading">
          <h3 id="artifact-engine-settings-heading" className="text-sm font-semibold text-ink">
            Aktuelle Artifact-Settings
          </h3>
          <dl className="mt-2 space-y-1 text-xs text-muted">
            <SettingRow label="Profil" value={artifactSettings.pii_profile} />
            <SettingRow
              label="Validierung"
              value={artifactSettings.candidate_validation_enabled ? "Aktiv" : "Deaktiviert"}
            />
            <SettingRow label="Schwellwert" value={artifactSettings.score_threshold.toFixed(2)} />
            <SettingRow label="Quelle" value={formatSource(artifactSettings.source)} />
          </dl>
        </section>
      ) : null}

      {devSettingsEnabled && config ? (
        <section aria-labelledby="dev-engine-settings-heading">
          <h3 id="dev-engine-settings-heading" className="text-sm font-semibold text-ink">
            Dev Engine Settings
          </h3>
          <p className="mt-1 text-xs text-muted">
            Nur fuer den naechsten PII-Lauf. Backend-Defaults bleiben unveraendert.
          </p>
          <label className="mt-3 block text-xs font-medium uppercase tracking-wide text-muted">
            PII-Profil
            <select
              value={selectedProfile}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                onProfileChange(event.target.value)
              }
              className="mt-2 w-full rounded-lg border border-card-border bg-white px-3 py-2 text-sm text-ink"
            >
              {profileOptions.map((option) => (
                <option key={option.value || "__default__"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <dl className="mt-3 space-y-1 text-xs text-muted">
            <SettingRow label="Backend-Default" value={config.defaultProfile} />
            <SettingRow
              label="Validierung"
              value={config.candidateValidationEnabled ? "Aktiv" : "Deaktiviert"}
            />
            <SettingRow label="Schwellwert" value={config.scoreThreshold.toFixed(2)} />
          </dl>
        </section>
      ) : null}
    </div>
  );
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt>{label}</dt>
      <dd className="break-all text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

function buildProfileOptions(config: PiiRuntimeConfig): Array<{ value: string; label: string }> {
  return [
    {
      value: "",
      label: `Backend-Default (${config.defaultProfile})`,
    },
    ...config.availableProfiles
      .filter((profile) => profile !== config.defaultProfile)
      .map((profile) => ({ value: profile, label: profile })),
  ];
}

function formatSource(source: PiiArtifactEngineSettings["source"]): string {
  return source === "dev-ui-override" ? "Dev-UI-Override" : "Server-Default";
}
