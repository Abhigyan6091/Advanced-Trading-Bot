"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { Badge, Card, ErrorState, Loading } from "@/components/ui";
import { PageHeader } from "@/components/page-header";

/**
 * AI Analyst.
 *
 * A read-only assistant over the platform's own records. Its tool registry
 * (app/ai/analyst.py on the backend) contains no order-placing or
 * limit-changing tool, so "the analyst cannot bypass the risk engine" is a
 * property of that registry -- checked by an architecture test -- rather than
 * a promise made in a prompt.
 */

const SUGGESTIONS = [
  "Why did my portfolio lose money today?",
  "Why was my most recent BTC trade rejected?",
  "Which strategy has performed best?",
  "What are my riskiest positions right now?",
];

interface Turn {
  question: string;
  answer?: string;
  toolsUsed?: string[];
  error?: string;
}

export default function AiAnalystPage() {
  const availability = useApi(() => api.aiAnalystAvailability());
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asking, setAsking] = useState(false);

  async function ask(q: string) {
    if (!q.trim() || asking) return;
    setAsking(true);
    setQuestion("");
    setTurns((prev) => [...prev, { question: q }]);

    try {
      const result = await api.aiAnalystAsk(q);
      setTurns((prev) =>
        prev.map((t, i) =>
          i === prev.length - 1
            ? { ...t, answer: result.answer, toolsUsed: result.tools_used }
            : t,
        ),
      );
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setTurns((prev) =>
        prev.map((t, i) => (i === prev.length - 1 ? { ...t, error: message } : t)),
      );
    } finally {
      setAsking(false);
    }
  }

  if (availability.error) return <ErrorState message={availability.error} />;

  return (
    <>
      <PageHeader
        title="AI Analyst"
        description="Ask questions about this account's own portfolio, trades and risk decisions. It answers only from what is actually stored — it cannot place, cancel or resize a trade."
      />

      {!availability.data ? (
        <Loading label="Checking availability" />
      ) : !availability.data.available ? (
        <Card title="Not configured">
          <div className="flex items-start gap-3">
            <Badge tone="accent">Setup required</Badge>
            <p className="max-w-2xl text-[13px] leading-relaxed text-ink-2">
              No <code className="font-mono">ANTHROPIC_API_KEY</code> is set on
              the backend, so the analyst is disabled. Every other feature on
              this platform works with no key at all — set the key and restart
              the API to enable this one.
            </p>
          </div>
        </Card>
      ) : (
        <Card
          title="Ask a question"
          subtitle={`Model: ${availability.data.model}`}
        >
          <div className="flex flex-col gap-4">
            {turns.length === 0 && (
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    className="rounded border border-rule bg-sunken px-2.5 py-1.5 text-left text-[12px] text-ink-2 hover:bg-accent-soft hover:text-accent"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            <div className="flex flex-col gap-4">
              {turns.map((turn, i) => (
                <div key={i} className="border-b border-rule/60 pb-4 last:border-0">
                  <p className="text-[13px] font-medium text-ink">{turn.question}</p>
                  {turn.error ? (
                    <p className="mt-2 text-[13px] text-critical">{turn.error}</p>
                  ) : turn.answer ? (
                    <>
                      <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">
                        {turn.answer}
                      </p>
                      {turn.toolsUsed && turn.toolsUsed.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {turn.toolsUsed.map((t, idx) => (
                            <code
                              key={`${t}-${idx}`}
                              className="rounded border border-rule bg-sunken px-1.5 py-0.5 font-mono text-[10px] text-muted"
                            >
                              {t}
                            </code>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="mt-2 text-[13px] text-muted">Thinking…</p>
                  )}
                </div>
              ))}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(question);
              }}
              className="flex gap-2"
            >
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask about your portfolio, trades or risk decisions…"
                disabled={asking}
                className="flex-1 rounded border border-rule bg-surface px-3 py-2 text-[13px] text-ink"
              />
              <button
                type="submit"
                disabled={asking || !question.trim()}
                className="rounded bg-accent px-4 py-2 text-[13px] font-medium text-white disabled:opacity-50"
              >
                {asking ? "Asking…" : "Ask"}
              </button>
            </form>
          </div>
        </Card>
      )}

      <Card
        className="mt-4"
        title="What it can and cannot do"
        subtitle="Structural, not a policy the model could be talked out of"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-good">
              Can
            </p>
            <ul className="space-y-1 text-[13px] text-ink-2">
              <li>Read the current portfolio, positions and P&amp;L</li>
              <li>Explain a specific risk decision, check by check</li>
              <li>Compare strategy performance</li>
              <li>Summarise recent orders and fills</li>
            </ul>
          </div>
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-critical">
              Cannot
            </p>
            <ul className="space-y-1 text-[13px] text-ink-2">
              <li>Place, cancel or resize an order</li>
              <li>Change a risk limit</li>
              <li>Bypass the risk engine — it has no tool that could</li>
            </ul>
          </div>
        </div>
      </Card>
    </>
  );
}
