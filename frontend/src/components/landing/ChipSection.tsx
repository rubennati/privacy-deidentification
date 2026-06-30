import { SectionHeading } from "./SectionHeading";

interface ChipSectionProps {
  title: string;
  intro?: string;
  items: readonly string[];
}

/** A section title with its items rendered as compact chips. Reused for info types and formats. */
export function ChipSection({ title, intro, items }: ChipSectionProps) {
  return (
    <section>
      <SectionHeading title={title} />
      {intro && <p className="mt-3 text-sm text-muted">{intro}</p>}

      <ul className="mt-5 flex flex-wrap gap-2">
        {items.map((item) => (
          <li
            key={item}
            className="rounded-full border border-card-border bg-card px-3.5 py-1.5 text-sm text-ink"
          >
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
