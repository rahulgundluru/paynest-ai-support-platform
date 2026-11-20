"use client";

/**
 * Live view of one pipeline run: every step, what it decided, how long it took and what the AI cost.
 * Status is never carried by colour alone: each step shows an icon AND a text label.
 */
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { formatIst, humanize } from "@/lib/format";
import { formatMs, formatUsd, type PipelineRun, type PipelineStep, type StepStatus } from "@/types/pipeline";

const PHASES: { title: string; caption: string; keys: string[] }[] = [
  { title: "Intake", caption: "Deterministic, before anything else sees the text", keys: ["received", "pii", "normalize", "customer_sla"] },
  { title: "Understand", caption: "Signals about the ticket", keys: ["duplicates", "injection", "classify"] },
  { title: "Decide and answer", caption: "Rules decide; the AI only drafts; a person approves", keys: ["routing", "retrieval", "draft", "validation", "review"] },
];

const KIND: Record<string, { label: string; tone: string }> = {
  pii: { label: "Security", tone: "border-danger/40 text-danger" },
  injection: { label: "Security", tone: "border-danger/40 text-danger" },
  classify: { label: "AI model", tone: "border-accent/50 text-accent" },
  draft: { label: "AI model", tone: "border-accent/50 text-accent" },
  validation: { label: "Rule checks", tone: "border-border text-text-muted" },
  routing: { label: "Rules R1–R9", tone: "border-border text-text-muted" },
  review: { label: "Person", tone: "border-success/40 text-success" },
};

export const STATUS: Record<StepStatus, { label: string; dot: string; text: string }> = {
  pending: { label: "Waiting", dot: "border-border bg-surface text-text-muted", text: "text-text-muted" },
  running: { label: "Running", dot: "border-accent bg-accent text-accent-contrast", text: "text-accent" },
  done: { label: "Done", dot: "border-success bg-success text-white", text: "text-success" },
  review: { label: "Needs a person", dot: "border-warning bg-warning text-white", text: "text-warning" },
  blocked: { label: "Blocked", dot: "border-danger bg-danger text-white", text: "text-danger" },
  failed: { label: "Failed", dot: "border-danger bg-danger text-white", text: "text-danger" },
  skipped: { label: "Skipped", dot: "border-dashed border-text-muted bg-surface text-text-muted", text: "text-text-muted" },
};

function StatusGlyph({ status }: { status: StepStatus }) {
  if (status === "running")
    return <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent-contrast/40 border-t-accent-contrast" aria-hidden />;
  const glyph = { pending: "", done: "✓", review: "!", blocked: "⦸", failed: "✕", skipped: "–" }[status];
  return (
    <span aria-hidden className="text-xs font-bold leading-none">
      {glyph}
    </span>
  );
}

function Pill({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{children}</span>;
}

/** Compact progress rail: one dot per step. */
export function PipelineRail({ steps }: { steps: PipelineStep[] }) {
  return (
    <ol className="flex items-center" aria-label="Pipeline progress">
      {steps.map((s, i) => (
        <li key={s.key} className="flex flex-1 items-center last:flex-none" title={`${s.label}: ${STATUS[s.status].label}`}>
          <span
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors duration-500 ${STATUS[s.status].dot} ${
              s.status === "running" ? "ring-4 ring-accent/20" : ""
            }`}
          >
            <StatusGlyph status={s.status} />
            <span className="sr-only">
              {s.label}: {STATUS[s.status].label}
            </span>
          </span>
          {i < steps.length - 1 && (
            <span
              className={`h-0.5 flex-1 transition-colors duration-500 ${
                s.status === "pending" || s.status === "running" ? "bg-border" : "bg-success/60"
              }`}
            />
          )}
        </li>
      ))}
    </ol>
  );
}

function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 text-xs">
      <span className="text-text-muted">{k}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function str(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Details({ step }: { step: PipelineStep }) {
  const d = step.details as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  switch (step.key) {
    case "pii":
      return (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1">
            {Object.entries((d.entities as Record<string, number>) ?? {}).map(([k, v]) => (
              <Pill key={k} className="border-danger/40 text-danger">
                {k} × {v}
              </Pill>
            ))}
          </div>
          {(d.tokens as string[] | undefined)?.length ? (
            <p className="text-xs text-text-muted">
              Stored as tokens: <span className="font-mono text-text">{(d.tokens as string[]).join(", ")}</span>. Originals are
              encrypted in the regional vault; only the DPO can reveal them, with a reason.
            </p>
          ) : null}
        </div>
      );
    case "routing":
      return (
        <div>
          <KV k="Rule">
            <span className="font-mono">{d.rule_id}</span> <span className="text-text-muted">({d.rule_version})</span>
          </KV>
          <KV k="Queue / level">
            {d.queue} · {d.support_level}
          </KV>
          <KV k="Lane">{humanize(d.lane)}</KV>
          <KV k="Approval required">{str(d.requires_approval)}</KV>
          <p className="mt-2 text-xs text-text-muted">{d.reason}</p>
          {d.inputs && (
            <p className="mt-2 font-mono text-[11px] text-text-muted">
              inputs: {Object.entries(d.inputs as Record<string, unknown>).map(([k, v]) => `${k}=${str(v)}`).join(" · ")}
            </p>
          )}
        </div>
      );
    case "classify":
      if (!d.model && !d.category) return <p className="text-xs text-text-muted">{str(d.reason ?? d.error)}</p>;
      return (
        <div>
          <KV k="Category">{humanize(d.category)}</KV>
          <KV k="Priority">{str(d.priority)}</KV>
          <KV k="Language">{str(d.language)}</KV>
          <KV k="Intent">{str(d.intent)}</KV>
          {typeof d.confidence === "number" && (
            <div className="mt-1">
              <KV k="Confidence">{(d.confidence as number).toFixed(2)}</KV>
              <div className="h-1.5 rounded bg-surface-muted">
                <div className="h-1.5 rounded bg-accent" style={{ width: `${Math.round((d.confidence as number) * 100)}%` }} />
              </div>
            </div>
          )}
          <KV k="Model">
            <span className="font-mono">{str(d.model)}</span>
          </KV>
        </div>
      );
    case "retrieval":
      return (
        <div className="space-y-2">
          <ul className="space-y-1">
            {((d.sources as Record<string, any>[]) ?? []).map((s) => ( // eslint-disable-line @typescript-eslint/no-explicit-any
              <li key={`${s.document_id}-${s.version}`} className="text-xs">
                <span className="font-mono">{s.document_id}</span> v{s.version} · {s.title}
                <span className="text-text-muted">
                  {" "}
                  · in force {s.effective_from ?? "always"} → {s.effective_to ?? "open"}
                  {s.content_complete === false ? " · title only" : ""}
                </span>
              </li>
            ))}
          </ul>
          {((d.rates as Record<string, string>[]) ?? []).length > 0 && (
            <div className="rounded-md bg-surface-muted p-2">
              <p className="text-[11px] font-medium text-text-muted">Statutory rates in force on {d.as_of}</p>
              {(d.rates as Record<string, string>[]).map((r) => (
                <p key={r.rule_id} className="text-xs">
                  <span className="font-mono">{r.rule_id}</span>: {r.value}
                </p>
              ))}
            </div>
          )}
        </div>
      );
    case "draft":
      if (!d.model) return <p className="text-xs text-text-muted">{str(d.reason ?? d.lane)}</p>;
      return (
        <div>
          <KV k="Model">
            <span className="font-mono">{d.model}</span>
          </KV>
          <KV k="Citations">{(d.citations as string[])?.join(", ") || "none"}</KV>
          <KV k="Tokens in / out">
            {str(d.input_tokens)} / {str(d.output_tokens)}
          </KV>
          <KV k="Attempts">{str(d.attempts)}</KV>
          {d.error && <KV k="Error">{str(d.error)}</KV>}
        </div>
      );
    case "validation":
      return (
        <ul className="space-y-0.5">
          {((d.checks as { name: string; passed: boolean; detail: string }[]) ?? []).map((c) => (
            <li key={c.name} className="flex items-start gap-2 text-xs">
              <span className={c.passed ? "text-success" : "text-danger"} aria-hidden>
                {c.passed ? "✓" : "✕"}
              </span>
              <span className="font-mono">{c.name}</span>
              <span className="text-text-muted">{c.passed ? "" : c.detail}</span>
              <span className="sr-only">{c.passed ? "passed" : "failed"}</span>
            </li>
          ))}
        </ul>
      );
    case "review":
      return d.approval_id ? (
        <Link href="/review" className="text-xs text-accent hover:underline">
          Open the review queue ({d.queue}) →
        </Link>
      ) : (
        <p className="text-xs text-text-muted">No review item: the queue handles it directly.</p>
      );
    case "duplicates":
      return (
        <div>
          <KV k="Outcome">{humanize(d.outcome)}</KV>
          {d.parent && (
            <KV k="Original ticket">
              <Link className="font-mono text-accent hover:underline" href={`/tickets/${d.parent}`}>
                {d.parent}
              </Link>
            </KV>
          )}
          {d.rule_id && <KV k="Rule">{d.rule_id}</KV>}
          {d.reason && <p className="mt-1 text-xs text-text-muted">{d.reason}</p>}
          {typeof d.recent_tickets === "number" && <KV k="Same customer, ±7 days">{d.recent_tickets} ticket(s)</KV>}
        </div>
      );
    default:
      return (
        <div>
          {Object.entries(d)
            .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
            .map(([k, v]) => (
              <KV key={k} k={humanize(k)}>
                {str(v)}
              </KV>
            ))}
        </div>
      );
  }
}

function StepCard({ step, last }: { step: PipelineStep; last: boolean }) {
  const [open, setOpen] = useState(false);
  const s = STATUS[step.status];
  const kind = KIND[step.key];
  const hasDetails = Object.keys(step.details ?? {}).length > 0;
  return (
    <li className="relative flex gap-3">
      <div className="flex flex-col items-center">
        <span
          className={`z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 transition-all duration-500 ${s.dot} ${
            step.status === "running" ? "ring-4 ring-accent/20" : ""
          }`}
        >
          <StatusGlyph status={step.status} />
        </span>
        {!last && <span className="w-0.5 flex-1 bg-border" />}
      </div>
      <div
        className={`mb-3 min-w-0 flex-1 rounded-lg border bg-surface p-3 transition-all duration-500 ${
          step.status === "running" ? "border-accent shadow-sm" : "border-border"
        } ${step.status === "pending" ? "opacity-60" : ""}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">{step.label}</h3>
          {kind && <Pill className={kind.tone}>{kind.label}</Pill>}
          <span className={`text-xs font-medium ${s.text}`}>{s.label}</span>
          <span className="ml-auto flex items-center gap-3 text-xs tabular-nums text-text-muted">
            {step.duration_ms !== null && step.status !== "pending" && step.status !== "running" && (
              <span title="Step duration">{formatMs(step.duration_ms)}</span>
            )}
            {step.cost_usd !== null && (
              <span className="font-medium text-text" title="Cost reported by the AI provider">
                {formatUsd(step.cost_usd)}
              </span>
            )}
          </span>
        </div>
        <p className="mt-1 text-sm">{step.summary ?? <span className="text-text-muted">{step.description}</span>}</p>
        {hasDetails && step.status !== "pending" && (
          <>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="mt-2 text-xs text-accent hover:underline"
            >
              {open ? "Hide details" : "Show details"}
            </button>
            {open && (
              <div className="mt-2 border-t border-border pt-2">
                <Details step={step} />
              </div>
            )}
          </>
        )}
      </div>
    </li>
  );
}

export function PipelineFlow({ run }: { run: PipelineRun }) {
  const byKey = Object.fromEntries(run.steps.map((s) => [s.key, s]));
  const finished = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  const seconds = (finished - new Date(run.started_at).getTime()) / 1000;
  const done = run.steps.filter((s) => !["pending", "running"].includes(s.status)).length;
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <span className="font-medium">
            {run.status === "running" ? (
              <span className="text-accent">Running… step {Math.min(done + 1, run.steps.length)} of {run.steps.length}</span>
            ) : run.status === "completed" ? (
              <span className="text-success">Completed</span>
            ) : (
              <span className="text-danger">Failed ({run.error})</span>
            )}
          </span>
          <span className="text-text-muted">
            {run.trigger === "create" ? "New ticket" : "Re-run"} · {formatIst(run.started_at)}
          </span>
          <span className="text-text-muted">Total {seconds.toFixed(1)} s</span>
          <span>
            AI cost <span className="font-semibold tabular-nums">{formatUsd(run.total_cost_usd)}</span>
          </span>
          <span className={run.ai_enabled ? "text-accent" : "text-text-muted"}>{run.ai_enabled ? "AI on" : "AI off"}</span>
        </div>
        <PipelineRail steps={run.steps} />
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        {PHASES.map((phase, index) => (
          <section key={phase.title} aria-labelledby={`phase-${index}`}>
            <h2 id={`phase-${index}`} className="text-xs font-semibold tracking-wide text-text-muted uppercase">
              {index + 1} · {phase.title}
            </h2>
            <p className="mb-3 text-xs text-text-muted">{phase.caption}</p>
            <ol>
              {phase.keys
                .filter((k) => byKey[k])
                .map((k, i, arr) => (
                  <StepCard key={k} step={byKey[k]!} last={i === arr.length - 1} />
                ))}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}
