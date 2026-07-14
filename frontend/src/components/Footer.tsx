import { Link } from "react-router-dom";

const LINKS = [
  { to: "/", label: "Start" },
  { to: "/upload", label: "Upload" },
  { to: "/documents", label: "Dokumente" },
] as const;

/** Global page footer: one privacy statement and the primary navigation, on every page. */
export function Footer() {
  return (
    <footer className="border-t border-card-border">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-3 px-4 py-6 text-xs text-muted sm:flex-row sm:px-6">
        <p>Alle Analysen laufen lokal auf diesem Server. Inhalte werden angezeigt, aber nie verändert.</p>
        <nav aria-label="Fußzeile" className="flex gap-4">
          {LINKS.map((link) => (
            <Link key={link.to} to={link.to} className="rounded transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none">
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
