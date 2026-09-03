"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4">
      <div className="w-full max-w-sm rounded-md border border-rule bg-surface p-6 shadow-sm">
        <p className="text-[13px] font-semibold leading-tight tracking-tight text-ink">
          Strategic Trade
          <br />
          Analyzer
        </p>
        <p className="mt-1 text-[10px] uppercase tracking-wider text-muted">
          Sign in to continue
        </p>

        <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-muted">
              Username
            </span>
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="rounded border border-rule bg-surface px-2.5 py-1.5 text-[13px] text-ink"
              autoComplete="username"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-muted">
              Password
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded border border-rule bg-surface px-2.5 py-1.5 text-[13px] text-ink"
              autoComplete="current-password"
            />
          </label>

          {error && <p className="text-[12px] text-critical">{error}</p>}

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="mt-1 rounded bg-accent px-3 py-1.5 text-[13px] font-medium text-white disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-4 text-[11px] leading-snug text-muted">
          Simulated trading only. No real money is ever at risk on this
          platform.
        </p>
      </div>
    </div>
  );
}
