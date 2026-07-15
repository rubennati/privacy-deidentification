import { useQuery } from "@tanstack/react-query";

import { fetchAppConfig, type AppConfig } from "../api/config";

export const appConfigKey = ["app-config"] as const;

/** The effective server config (dev-gate, runtime capabilities, PII profiles). It rarely changes,
 *  so cache it app-wide instead of re-fetching on every document mount. `fetchAppConfig` resolves
 *  to `null` when the request fails, so consumers stay null-tolerant. */
export function useAppConfig() {
  return useQuery<AppConfig | null>({
    queryKey: appConfigKey,
    queryFn: fetchAppConfig,
    staleTime: 5 * 60_000,
  });
}
