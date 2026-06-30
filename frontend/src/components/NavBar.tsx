import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/", label: "Start" },
  { to: "/upload", label: "Upload" },
  { to: "/documents", label: "Dokumente" },
] as const;

/** Minimal top navigation shared by every page. */
export function NavBar() {
  return (
    <nav className="flex justify-center gap-1 border-b border-card-border bg-page px-4 py-3">
      {LINKS.map((link) => (
        <NavLink
          key={link.to}
          to={link.to}
          end={link.to === "/"}
          className={({ isActive }) =>
            [
              "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
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
  );
}
