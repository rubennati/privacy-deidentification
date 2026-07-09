// Fetches the effective app config from the backend (the single source of truth),
// so client-side validation messages and safe dev-only engine controls mirror the server
// instead of hardcoding their own copy. Falls back to null if the request fails.

export interface UploadConfig {
  maxUploadBytes: number;
  allowedExtensions: string[];
}

export interface PiiRuntimeConfig {
  defaultProfile: string;
  availableProfiles: string[];
  candidateValidationEnabled: boolean;
  scoreThreshold: number;
}

// Whether the optional OCR/PII runtimes are actually installed on this server (not whether a
// given document has been analyzed). A read-only signal only — it never gates a request; it lets
// the UI show a proactive hint instead of only discovering "not installed" via a 503.
export interface RuntimeCapabilities {
  ocrAvailable: boolean;
  piiAvailable: boolean;
  /** OCR is installed but the API memory limit looks too low for explicit sync fallback mode. */
  ocrMemoryLimitLow: boolean;
}

export interface AppConfig extends UploadConfig {
  devEngineSettingsEnabled: boolean;
  pii: PiiRuntimeConfig;
  runtime: RuntimeCapabilities;
}

interface ConfigResponse {
  max_upload_bytes: number;
  allowed_extensions: string[];
  dev_engine_settings_enabled: boolean;
  pii: {
    default_profile: string;
    available_profiles: string[];
    candidate_validation_enabled: boolean;
    score_threshold: number;
  };
  runtime: {
    ocr_available: boolean;
    pii_available: boolean;
    ocr_memory_limit_low: boolean;
  };
}

export async function fetchAppConfig(): Promise<AppConfig | null> {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      return null;
    }
    const data = (await response.json()) as ConfigResponse;
    return {
      maxUploadBytes: data.max_upload_bytes,
      allowedExtensions: data.allowed_extensions,
      devEngineSettingsEnabled: data.dev_engine_settings_enabled,
      pii: {
        defaultProfile: data.pii.default_profile,
        availableProfiles: data.pii.available_profiles,
        candidateValidationEnabled: data.pii.candidate_validation_enabled,
        scoreThreshold: data.pii.score_threshold,
      },
      runtime: {
        ocrAvailable: data.runtime.ocr_available,
        piiAvailable: data.runtime.pii_available,
        ocrMemoryLimitLow: data.runtime.ocr_memory_limit_low,
      },
    };
  } catch {
    return null;
  }
}

export async function fetchUploadConfig(): Promise<UploadConfig | null> {
  const config = await fetchAppConfig();
  if (!config) {
    return null;
  }
  return {
    maxUploadBytes: config.maxUploadBytes,
    allowedExtensions: config.allowedExtensions,
  };
}
