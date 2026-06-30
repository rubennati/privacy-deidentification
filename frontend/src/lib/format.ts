// Small display formatters for the documents list.

const SIZE_UNITS = ["B", "KB", "MB", "GB"] as const;

/** Format a byte count as a short human-readable size, e.g. 123456 -> "120,6 KB". */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) {
    return "0 B";
  }
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    SIZE_UNITS.length - 1,
  );
  const value = bytes / 1024 ** exponent;
  const formatted = exponent === 0 ? String(value) : value.toFixed(1).replace(".", ",");
  return `${formatted} ${SIZE_UNITS[exponent]}`;
}

const timestampFormatter = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Format a UTC ISO 8601 timestamp for display, e.g. "30. Juni 2026, 18:00". */
export function formatTimestamp(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) {
    return isoTimestamp;
  }
  return timestampFormatter.format(date);
}
