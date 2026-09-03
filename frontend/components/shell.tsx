"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";

const SECTIONS = [
  { href: "/", label: "Overview" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/markets", label: "Markets" },
  { href: "/trade", label: "Trade" },
  { href: "/orders", label: "Orders" },
  { href: "/risk", label: "Risk" },
  { href: "/strategies", label: "Strategies" },
  { href: "/backtesting", label: "Backtesting" },
  { href: "/performance", label: "Performance" },
  { href: "/ai-analyst", label: "AI Analyst" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);

  useEffect(() => {
    const stored = (() => {
      try {
        return localStorage.getItem("sta-theme");
      } catch {
        return null;
      }
    })();
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
      document.documentElement.setAttribute("data-theme", stored);
    }
  }, []);

  const toggle = () => {
    const next =
      theme === "dark"
        ? "light"
        : theme === "light"
          ? "dark"
          : window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "light"
            : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("sta-theme", next);
    } catch {
      /* private mode: the choice simply does not persist */
    }
  };

  return (
    <button
      onClick={toggle}
      className="rounded border border-rule px-2 py-1 text-[11px] text-ink-2 hover:bg-sunken"
      aria-label="Toggle colour theme"
    >
      {theme === "dark" ? "☀ Light" : "☾ Dark"}
    </button>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  if (!user) return null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-muted">
        {user.username} <span className="text-ink-2">· {user.role}</span>
      </span>
      <button
        onClick={() => {
          logout();
          router.push("/login");
        }}
        className="rounded border border-rule px-2 py-1 text-[11px] text-ink-2 hover:bg-sunken"
      >
        Sign out
      </button>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading } = useAuth();
  const isLoginPage = pathname === "/login";

  useEffect(() => {
    if (!loading && !user && !isLoginPage) {
      router.replace("/login");
    }
  }, [loading, user, isLoginPage, router]);

  // The login page renders on its own, full-screen, with no sidebar/nav.
  if (isLoginPage) return <>{children}</>;

  // Waiting to know whether a stored token is valid, or already redirecting:
  // render nothing rather than flashing protected content or a broken shell.
  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page">
        <p className="text-[13px] text-muted">Loading…</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-r border-rule bg-surface lg:block">
        <div className="border-b border-rule px-4 py-4">
          <p className="text-[13px] font-semibold leading-tight tracking-tight text-ink">
            Strategic Trade
            <br />
            Analyzer
          </p>
          <p className="mt-1 text-[10px] uppercase tracking-wider text-muted">
            Trading &amp; risk analysis
          </p>
        </div>

        <nav className="p-2" aria-label="Sections">
          {SECTIONS.map((s) => {
            const active = pathname === s.href;
            return (
              <Link
                key={s.href}
                href={s.href}
                aria-current={active ? "page" : undefined}
                className={`block rounded px-3 py-1.5 text-[13px] transition-colors ${
                  active
                    ? "bg-accent-soft font-medium text-accent"
                    : "text-ink-2 hover:bg-sunken"
                }`}
              >
                {s.label}
              </Link>
            );
          })}
        </nav>

        <div className="mx-3 mt-2 rounded border border-rule bg-sunken px-3 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-accent">
            Simulated only
          </p>
          <p className="mt-1 text-[11px] leading-snug text-muted">
            Real-money execution is not implemented. There is no live broker to
            enable.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-rule bg-surface px-5 py-3">
          <div className="flex items-center gap-3">
            <span className="lg:hidden text-[13px] font-semibold text-ink">
              Strategic Trade Analyzer
            </span>
            <span className="hidden text-[13px] font-semibold text-ink lg:inline">
              {SECTIONS.find((s) => s.href === pathname)?.label ?? "Overview"}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="rounded border border-rule bg-sunken px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
              paper broker
            </span>
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>

        {/* Mobile navigation: the sidebar collapses below lg. */}
        <nav
          className="flex gap-1 overflow-x-auto border-b border-rule bg-surface px-3 py-2 lg:hidden"
          aria-label="Sections"
        >
          {SECTIONS.map((s) => (
            <Link
              key={s.href}
              href={s.href}
              className={`whitespace-nowrap rounded px-2.5 py-1 text-[12px] ${
                pathname === s.href
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-ink-2"
              }`}
            >
              {s.label}
            </Link>
          ))}
        </nav>

        <main className="min-w-0 flex-1 p-5">{children}</main>
      </div>
    </div>
  );
}
