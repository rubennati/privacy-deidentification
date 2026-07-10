import type { PiiValidationSummary } from "../../api/workstations";

interface PiiValidationTransparencyProps {
  validation: PiiValidationSummary | null | undefined;
}

export function PiiValidationTransparency({ validation }: PiiValidationTransparencyProps) {
  return (
    <section className="mt-4 rounded-lg border border-card-border bg-dropzone p-4">
      <h3 className="text-sm font-semibold text-ink">Kandidatenvalidierung</h3>
      {!validation ? (
        <p className="mt-2 text-xs text-muted">
          Für dieses ältere PII-Ergebnis ist kein Validierungsbericht gespeichert.
        </p>
      ) : !validation.enabled ? (
        <p className="mt-2 text-xs text-muted">
          Die Kandidatenvalidierung war für diesen PII-Lauf deaktiviert.
        </p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-3 gap-3 text-xs">
            <Metric label="Beibehalten" value={validation.kept} />
            <Metric label="Verworfen" value={validation.dropped} />
            <Metric label="Abgewertet" value={validation.score_down} />
          </dl>
          <ReasonCounts title="Gründe für verworfene Kandidaten" counts={validation.dropped_by_reason} />
          <ReasonCounts title="Gründe für abgewertete Kandidaten" counts={validation.score_down_by_reason} />
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="mt-1 text-base font-semibold text-ink">{value}</dd>
    </div>
  );
}

function ReasonCounts({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort(([left], [right]) => left.localeCompare(right));
  if (entries.length === 0) return null;

  return (
    <div className="mt-4">
      <h4 className="text-xs font-medium text-muted">{title}</h4>
      <dl className="mt-2 space-y-1 font-mono text-xs text-ink">
        {entries.map(([reason, count]) => (
          <div key={reason} className="flex justify-between gap-3">
            <dt className="break-all">{reason}</dt>
            <dd className="font-semibold">{count}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
