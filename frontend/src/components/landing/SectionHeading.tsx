interface SectionHeadingProps {
  title: string;
  id?: string;
}

/** Consistent section title used across the landing page. */
export function SectionHeading({ title, id }: SectionHeadingProps) {
  return (
    <h2 id={id} className="text-lg font-semibold text-ink sm:text-xl">
      {title}
    </h2>
  );
}
