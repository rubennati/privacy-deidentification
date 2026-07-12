import { Link, NavLink } from "react-router-dom";

const LINKS = [
  { to: "/", label: "Start" },
  { to: "/upload", label: "Upload" },
  { to: "/documents", label: "Dokumente" },
] as const;

/** Top navigation shared by every page: wordmark on the left, primary navigation on the right. */
export function NavBar() {
  return (
    <header className="border-b border-card-border bg-page">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link
          to="/"
          className="flex items-center gap-2 rounded-lg text-sm font-semibold tracking-tight text-ink transition-colors hover:text-accent-dark focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          <ShieldIcon />
          Privacy Pilot
        </Link>
        <nav aria-label="Hauptnavigation" className="flex gap-1">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              className={({ isActive }) =>
                [
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
                  isActive
                    ? "bg-accent-soft text-accent-dark"
                    : "text-muted hover:bg-accent-soft/60 hover:text-ink",
                ].join(" ")
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="text-accent"
    >
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}
