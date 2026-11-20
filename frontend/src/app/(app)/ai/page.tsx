"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ChartCard, ColumnChart, StatTile } from "@/components/charts";
import { Alert, Badge, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst, humanize } from "@/lib/format";
import type { Page } from "@/types/api";
import {
  formatMs,
  formatUsd,
  type AiAccount,
  type AiCall,
  type AiCatalogueModel,
  type AiConfigView,
  type AiOverview,
  type AiStatus,
} from "@/types/pipeline";

type Tab = "overview" | "calls" | "config";

const STATE_LABEL: Record<AiStatus["state"], { text: string; tone: "success" | "warning" | "danger" }> = {
  on: { text: "AI on", tone: "success" },
  off: { text: "AI off", tone: "warning" },
  no_model: { text: "No model selected", tone: "warning" },
  no_key: { text: "No API key on the server", tone: "danger" },
  not_configured: { text: "Provider not configured", tone: "danger" },
};

function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const tone = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-accent";
  return (
    <div>
      <div
        className="h-2 rounded-full bg-surface-muted"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
      >
        <div className={`h-2 rounded-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-text-muted tabular-nums">{pct.toFixed(pct < 1 && pct > 0 ? 2 : 0)}% used</p>
    </div>
  );
}

function StatusBanner({ status }: { status: AiStatus }) {
  const s = STATE_LABEL[status.state];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
      <Badge tone={s.tone === "success" ? "success" : s.tone === "danger" ? "danger" : "neutral"}>{s.text}</Badge>
      <span className="text-text-muted">{status.note}</span>
      <span className="ml-auto text-xs text-text-muted">
        Classifier <span className="font-mono text-text">{status.classifier_model ?? "—"}</span> · Drafts{" "}
        <span className="font-mono text-text">{status.drafting_model ?? "—"}</span>
      </span>
    </div>
  );
}

function Mini({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-md bg-surface-muted p-3">
      <p className="text-xs text-text-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}

// --------------------------------------------------------------------------------------------- overview
function Overview() {
  const [days, setDays] = useState(14);
  const q = useQuery<AiOverview>({
    queryKey: ["ai-overview", days],
    queryFn: () => apiFetch(`/api/v1/ai/overview?days=${days}`),
    placeholderData: keepPreviousData,
    refetchInterval: 15000,
  });
  if (q.isLoading) return <Spinner label="Loading AI usage" />;
  if (q.isError || !q.data) return <Alert tone="danger">Could not load AI usage.</Alert>;
  const o = q.data;
  const successRate = o.period.calls ? (o.period.successful / o.period.calls) * 100 : null;
  const draftOk = o.period.avg_cost_per_draft_usd !== null && o.period.avg_cost_per_draft_usd <= o.period.draft_target_usd;

  return (
    <div className="space-y-4">
      <StatusBanner status={o.status} />
      <div className="flex items-center justify-end gap-2 text-sm">
        <span className="text-text-muted">Window</span>
        {[7, 14, 30].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            aria-pressed={days === d}
            className={`rounded-md border px-2 py-1 text-xs ${days === d ? "border-accent bg-accent/10 text-accent" : "border-border"}`}
          >
            {d} days
          </button>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-border bg-surface p-4">
          <p className="text-xs text-text-muted">Spent today (IST)</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{formatUsd(o.today.cost_usd)}</p>
          <p className="mb-2 text-xs text-text-muted">of {formatUsd(o.today.budget_usd)} daily cap · {o.today.calls} calls</p>
          <Meter value={o.today.cost_usd} max={o.today.budget_usd} label="Daily AI budget used" />
        </div>
        <StatTile label="This month" value={formatUsd(o.month.cost_usd)} sub={`${o.month.calls} calls · ${o.month.tickets} tickets`} />
        <StatTile
          label="Average AI cost per ticket"
          value={formatUsd(o.period.avg_cost_per_ticket_usd)}
          sub={o.period.max_cost_per_ticket_usd !== null ? `highest ${formatUsd(o.period.max_cost_per_ticket_usd)} · last ${days} days` : "no AI-processed tickets yet"}
        />
        <StatTile
          label="Average cost per draft"
          value={formatUsd(o.period.avg_cost_per_draft_usd)}
          sub={
            o.period.avg_cost_per_draft_usd === null
              ? `target ≤ ${formatUsd(o.period.draft_target_usd)}`
              : `${draftOk ? "✓ within" : "✕ above"} the ${formatUsd(o.period.draft_target_usd)} target`
          }
        />
        <StatTile label="Model calls" value={o.period.calls} sub={successRate === null ? "—" : `${successRate.toFixed(1)}% succeeded`} />
        <StatTile label="Latency p50 / p95" value={`${formatMs(o.period.latency_ms_p50)} / ${formatMs(o.period.latency_ms_p95)}`} sub="successful calls" />
        <StatTile label="Tokens in / out" value={`${o.period.input_tokens.toLocaleString()} / ${o.period.output_tokens.toLocaleString()}`} />
        <StatTile
          label="Cost source"
          value={`${o.period.provider_reported_cost_calls} / ${o.period.calls}`}
          sub="calls priced by the provider's own report"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="AI spend per day"
          description="Sum of provider-reported cost per IST day."
          table={{ columns: ["Date", "Calls", "Failed", "Cost (USD)"], rows: o.by_day.map((d) => [d.date, d.calls, d.failed, d.cost_usd.toFixed(5)]) }}
        >
          <ColumnChart
            data={o.by_day.map((d) => ({ label: d.date.slice(5), value: d.cost_usd, extra: `${d.calls} calls` }))}
            valueLabel="Cost"
            format={(v) => formatUsd(v)}
            axisFormat={(v) => `$${v.toFixed(3)}`}
          />
        </ChartCard>
        <ChartCard
          title="Model calls per day"
          table={{ columns: ["Date", "Calls", "Failed"], rows: o.by_day.map((d) => [d.date, d.calls, d.failed]) }}
        >
          <ColumnChart data={o.by_day.map((d) => ({ label: d.date.slice(5), value: d.calls, extra: `${d.failed} failed` }))} valueLabel="Calls" />
        </ChartCard>
      </div>

      <Card title="By model and step">
        {o.by_model.length === 0 ? (
          <p className="text-sm text-text-muted">No model calls in this window.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Model</th>
                  <th className="py-1 pr-3 font-medium">Step</th>
                  <th className="py-1 pr-3 text-right font-medium">Calls</th>
                  <th className="py-1 pr-3 text-right font-medium">OK</th>
                  <th className="py-1 pr-3 text-right font-medium">Tokens in / out</th>
                  <th className="py-1 pr-3 text-right font-medium">p50 / p95</th>
                  <th className="py-1 pr-3 text-right font-medium">Avg / call</th>
                  <th className="py-1 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {o.by_model.map((m) => (
                  <tr key={`${m.model}-${m.operation}`} className="border-t border-border tabular-nums">
                    <td className="py-1.5 pr-3 font-mono text-xs">{m.model}</td>
                    <td className="py-1.5 pr-3">{m.operation === "classify" ? "Classification" : m.operation === "draft" ? "Draft" : m.operation}</td>
                    <td className="py-1.5 pr-3 text-right">{m.calls}</td>
                    <td className="py-1.5 pr-3 text-right">{m.successful}</td>
                    <td className="py-1.5 pr-3 text-right">
                      {m.input_tokens.toLocaleString()} / {m.output_tokens.toLocaleString()}
                    </td>
                    <td className="py-1.5 pr-3 text-right">
                      {formatMs(m.latency_ms_p50)} / {formatMs(m.latency_ms_p95)}
                    </td>
                    <td className="py-1.5 pr-3 text-right">{formatUsd(m.avg_cost_usd)}</td>
                    <td className="py-1.5 text-right font-medium">{formatUsd(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Guardrails" className="lg:col-span-2">
          <div className="grid gap-2 sm:grid-cols-3">
            <Mini label="Calls blocked for personal data" value={o.guardrails.pii_blocked_calls} hint="PII guard at the network boundary" />
            <Mini label="Tickets never sent to the model" value={o.guardrails.injection_skips} hint="injection screen (rule R1)" />
            <Mini label="Steps stopped by a budget cap" value={o.guardrails.budget_stops} hint="daily or per-ticket cap" />
            <Mini label="Malformed model outputs" value={o.guardrails.schema_failures} hint="rejected by schema validation" />
            <Mini label="AI drafts that passed validation" value={o.guardrails.drafts_passed_validation} />
            <Mini label="AI drafts that failed validation" value={o.guardrails.drafts_failed_validation} hint="cannot be approved until fixed" />
          </div>
          {Object.keys(o.guardrails.provider_errors).length > 0 && (
            <p className="mt-3 text-xs text-text-muted">
              Provider errors:{" "}
              {Object.entries(o.guardrails.provider_errors).map(([k, v]) => (
                <span key={k} className="mr-2 font-mono">
                  {k} × {v}
                </span>
              ))}
            </p>
          )}
        </Card>
        <Card title="Monthly projection">
          {o.projection ? (
            <div className="space-y-2">
              <p className="text-2xl font-semibold tabular-nums">{formatUsd(o.projection.monthly_model_cost_usd)}</p>
              <p className="text-xs text-text-muted">
                per month at {formatUsd(o.projection.avg_cost_per_ticket_usd)} × {o.projection.tickets_per_month.toLocaleString()} tickets,
                against the {formatUsd(o.projection.budget_cap_usd)} monthly cap
              </p>
              <Meter value={o.projection.monthly_model_cost_usd} max={o.projection.budget_cap_usd} label="Projected share of monthly cap" />
              <p className="text-[11px] text-text-muted">
                Basis: {o.projection.basis}. Sample: {o.projection.sample_tickets} ticket(s), so treat a small sample with care.
              </p>
            </div>
          ) : (
            <p className="text-sm text-text-muted">Process at least one ticket with AI on to project a monthly cost from measured data.</p>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Pipeline runs">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Mini label="Runs" value={o.runs.total} />
            <Mini label="Completed" value={o.runs.completed} />
            <Mini label="Failed" value={o.runs.failed} />
            <Mini label="Average duration" value={o.runs.avg_duration_s !== null ? `${o.runs.avg_duration_s.toFixed(1)} s` : "—"} />
          </div>
          <p className="mt-2 text-xs text-text-muted">Average AI cost per completed run: {formatUsd(o.runs.avg_cost_usd)}</p>
        </Card>
        <Card title="Most expensive tickets">
          {o.top_tickets.length === 0 ? (
            <p className="text-sm text-text-muted">None yet.</p>
          ) : (
            <ul className="divide-y divide-border text-sm">
              {o.top_tickets.map((t) => (
                <li key={t.ticket} className="flex justify-between py-1.5">
                  <Link href={`/tickets/${t.ticket}/flow`} className="font-mono text-accent hover:underline">
                    {t.ticket}
                  </Link>
                  <span className="tabular-nums text-text-muted">
                    {t.calls} calls · <span className="text-text">{formatUsd(t.cost_usd)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------------------------- call log
function Calls() {
  const [page, setPage] = useState(1);
  const [operation, setOperation] = useState("");
  const [outcome, setOutcome] = useState("");
  const [ticket, setTicket] = useState("");
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (operation) params.set("operation", operation);
  if (outcome) params.set("outcome", outcome);
  if (ticket.trim()) params.set("ticket", ticket.trim());
  const q = useQuery<Page<AiCall>>({
    queryKey: ["ai-calls", params.toString()],
    queryFn: () => apiFetch(`/api/v1/ai/calls?${params}`),
    placeholderData: keepPreviousData,
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  const sel = "rounded-md border border-border bg-surface px-2 py-2 text-sm";
  return (
    <Card>
      <div className="mb-3 flex flex-wrap gap-2">
        <select aria-label="Step" className={sel} value={operation} onChange={(e) => (setPage(1), setOperation(e.target.value))}>
          <option value="">All steps</option>
          <option value="classify">Classification</option>
          <option value="draft">Draft</option>
        </select>
        <select aria-label="Outcome" className={sel} value={outcome} onChange={(e) => (setPage(1), setOutcome(e.target.value))}>
          <option value="">All outcomes</option>
          <option value="success">Succeeded</option>
          <option value="failed">Failed</option>
        </select>
        <Input aria-label="Ticket id" placeholder="Ticket, e.g. PN-200001" value={ticket} onChange={(e) => (setPage(1), setTicket(e.target.value))} className="w-56" />
      </div>
      {q.isLoading ? (
        <Spinner label="Loading calls" />
      ) : q.data && q.data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-text-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Time</th>
                <th className="py-1 pr-3 font-medium">Ticket</th>
                <th className="py-1 pr-3 font-medium">Step</th>
                <th className="py-1 pr-3 font-medium">Model (served by)</th>
                <th className="py-1 pr-3 text-right font-medium">Tokens</th>
                <th className="py-1 pr-3 text-right font-medium">Latency</th>
                <th className="py-1 pr-3 text-right font-medium">Cost</th>
                <th className="py-1 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((c) => (
                <tr key={c.id} className="border-t border-border tabular-nums">
                  <td className="py-1.5 pr-3 text-xs whitespace-nowrap">{formatIst(c.created_at)}</td>
                  <td className="py-1.5 pr-3">
                    {c.ticket ? (
                      <Link href={`/tickets/${c.ticket}/flow`} className="font-mono text-accent hover:underline">
                        {c.ticket}
                      </Link>
                    ) : (
                      <span className="text-xs text-text-muted">{c.prompt_version === "connection-test" ? "connection test" : "—"}</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-3">{c.operation === "classify" ? "Classification" : c.operation === "draft" ? "Draft" : c.operation}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs">
                    {c.model}
                    {c.upstream_provider && <span className="text-text-muted"> ({c.upstream_provider})</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-right">
                    {c.input_tokens} / {c.output_tokens}
                  </td>
                  <td className="py-1.5 pr-3 text-right">{formatMs(c.latency_ms)}</td>
                  <td className="py-1.5 pr-3 text-right" title={c.cost_source ? humanize(c.cost_source) : "cost not reported"}>
                    {formatUsd(c.cost_usd)}
                  </td>
                  <td className="py-1.5">{c.success ? <Badge tone="success">ok</Badge> : <Badge tone="danger">{c.error ?? "failed"}</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-text-muted">No model calls match.</p>
      )}
      <div className="mt-3 flex items-center justify-between text-sm">
        <span className="text-text-muted">{q.data?.total ?? 0} calls</span>
        <div className="flex items-center gap-2">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="tabular-nums">
            {page} / {pages}
          </span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>
    </Card>
  );
}

// --------------------------------------------------------------------------------------- models and limits
function ModelPicker({
  id,
  label,
  value,
  onChange,
  models,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  models: AiCatalogueModel[];
  disabled: boolean;
}) {
  const [filter, setFilter] = useState("");
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return models.filter((m) => !f || m.id.toLowerCase().includes(f) || m.name.toLowerCase().includes(f)).slice(0, 200);
  }, [filter, models]);
  const current = models.find((m) => m.id === value);
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium text-text-muted">
        {label}
      </label>
      <Input placeholder="Filter models, e.g. haiku, mini, flash" value={filter} onChange={(e) => setFilter(e.target.value)} disabled={disabled} aria-label={`Filter ${label}`} />
      <select
        id={id}
        className="w-full rounded-md border border-border bg-surface px-2 py-2 font-mono text-xs"
        size={6}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— none (step skipped) —</option>
        {value && !current && <option value={value}>{value} (not in the current list)</option>}
        {shown.map((m) => (
          <option key={m.id} value={m.id}>
            {m.id} · ${m.input_usd_per_mtok.toFixed(2)} in / ${m.output_usd_per_mtok.toFixed(2)} out per 1M
          </option>
        ))}
      </select>
      <p className="text-xs text-text-muted">
        {current
          ? `${current.name}: $${current.input_usd_per_mtok.toFixed(3)} / $${current.output_usd_per_mtok.toFixed(3)} per 1M tokens (in / out), list price`
          : value
            ? "Selected model"
            : "No model selected"}
      </p>
    </div>
  );
}

function Config() {
  const queryClient = useQueryClient();
  const cfg = useQuery<AiConfigView>({ queryKey: ["ai-config"], queryFn: () => apiFetch("/api/v1/ai/config") });
  const models = useQuery<{ items: AiCatalogueModel[] }>({
    queryKey: ["ai-models"],
    queryFn: () => apiFetch("/api/v1/ai/models"),
    staleTime: 3_600_000,
  });
  const canManage = !!cfg.data?.can_manage;
  const account = useQuery<AiAccount>({
    queryKey: ["ai-account"],
    queryFn: () => apiFetch("/api/v1/ai/account"),
    enabled: canManage && !!cfg.data?.status.key_configured,
    retry: false,
  });
  const [draft, setDraft] = useState<Record<string, boolean | number | string | null>>({});
  useEffect(() => {
    if (cfg.data) setDraft(Object.fromEntries(cfg.data.settings.map((s) => [s.key, s.value])));
  }, [cfg.data]);
  const save = useMutation({
    mutationFn: (changes: Record<string, unknown>) =>
      apiFetch<AiConfigView>("/api/v1/ai/config", { method: "PATCH", body: JSON.stringify({ changes }) }),
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-config"], data);
      queryClient.invalidateQueries({ queryKey: ["ai-overview"] });
      queryClient.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });
  const test = useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; model?: string; upstream_provider?: string; latency_ms?: number; cost_usd?: number | null; category?: string; confidence?: number; error?: string; code?: string }>(
        "/api/v1/ai/test",
        { method: "POST" },
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["ai-overview"] }),
  });

  if (cfg.isLoading) return <Spinner label="Loading AI settings" />;
  if (cfg.isError || !cfg.data) return <Alert tone="danger">Could not load AI settings.</Alert>;
  const settings = Object.fromEntries(cfg.data.settings.map((s) => [s.key, s]));
  const changed = Object.fromEntries(
    Object.entries(draft).filter(([k, v]) => settings[k] && (settings[k].value ?? "") !== (v ?? "")),
  );
  const num = (k: string) => (
    <Input
      id={k}
      type="number"
      step="0.001"
      min={settings[k]?.minimum ?? undefined}
      max={settings[k]?.maximum ?? undefined}
      value={draft[k] === null || draft[k] === undefined ? "" : String(draft[k])}
      disabled={!canManage}
      onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value === "" ? null : Number(e.target.value) }))}
    />
  );

  return (
    <div className="space-y-4">
      <StatusBanner status={cfg.data.status} />
      {!canManage && <Alert tone="warning">You can view these settings; only an administrator can change them.</Alert>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Models and switch" className="lg:col-span-2">
          <div className="space-y-4">
            <label className="flex items-center gap-3 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--accent)]"
                checked={!!draft["ai.enabled"]}
                disabled={!canManage}
                onChange={(e) => setDraft((d) => ({ ...d, "ai.enabled": e.target.checked }))}
              />
              <span>
                <span className="font-medium">Use the AI model</span>
                <span className="block text-xs text-text-muted">Off: every rule still runs; classification uses the customer&apos;s pick and agents write replies.</span>
              </span>
            </label>
            {models.isError && <Alert tone="warning">Could not load OpenRouter&apos;s model list; current selections are kept.</Alert>}
            <div className="grid gap-4 md:grid-cols-2">
              <ModelPicker
                id="classifier"
                label="Classification model"
                value={String(draft["ai.classifier_model"] ?? "")}
                onChange={(v) => setDraft((d) => ({ ...d, "ai.classifier_model": v || null }))}
                models={models.data?.items ?? []}
                disabled={!canManage}
              />
              <ModelPicker
                id="drafter"
                label="Drafting model"
                value={String(draft["ai.drafting_model"] ?? "")}
                onChange={(v) => setDraft((d) => ({ ...d, "ai.drafting_model": v || null }))}
                models={models.data?.items ?? []}
                disabled={!canManage}
              />
            </div>
            <p className="text-xs text-text-muted">
              Only models that support tool calling and have a fixed price are listed, cheapest first. Requests also require providers
              that neither collect nor retain prompts, so some models may have no eligible endpoint; the connection test shows this.
            </p>
          </div>
        </Card>
        <Card title="Spending caps">
          <div className="space-y-3">
            <div className="space-y-1">
              <label htmlFor="ai.daily_budget_usd" className="text-xs font-medium text-text-muted">
                Daily cap (USD, IST day)
              </label>
              {num("ai.daily_budget_usd")}
            </div>
            <div className="space-y-1">
              <label htmlFor="ai.ticket_budget_usd" className="text-xs font-medium text-text-muted">
                Per-ticket cap (USD)
              </label>
              {num("ai.ticket_budget_usd")}
            </div>
            <p className="text-xs text-text-muted">
              Checked before every model call. When a cap is reached the step is skipped and the ticket goes to a person.
            </p>
          </div>
        </Card>
      </div>

      {canManage && (
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={save.isPending || Object.keys(changed).length === 0} onClick={() => save.mutate(changed)}>
            {save.isPending ? "Saving…" : `Save changes${Object.keys(changed).length ? ` (${Object.keys(changed).length})` : ""}`}
          </Button>
          <Button variant="secondary" disabled={test.isPending || !cfg.data.status.classifier_model} onClick={() => test.mutate()}>
            {test.isPending ? "Testing…" : "Test connection (1 small billed call)"}
          </Button>
          {save.isSuccess && <span className="text-sm text-success">Saved and audited.</span>}
        </div>
      )}
      {save.isError && <Alert tone="danger">{save.error instanceof ApiError ? save.error.message : "Could not save."}</Alert>}
      {test.data &&
        (test.data.ok ? (
          <Alert tone="success">
            Connected: <span className="font-mono">{test.data.model}</span> via {test.data.upstream_provider ?? "OpenRouter"} in{" "}
            {formatMs(test.data.latency_ms)}, cost {formatUsd(test.data.cost_usd ?? null)}. A synthetic how-to question was classified as{" "}
            {humanize(test.data.category ?? "")} ({test.data.confidence}).
          </Alert>
        ) : (
          <Alert tone="danger">
            Connection failed ({test.data.code}): {test.data.error}
          </Alert>
        ))}
      {test.isError && <Alert tone="danger">{test.error instanceof ApiError ? test.error.message : "Test failed."}</Alert>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Privacy">
          <ul className="space-y-1 text-sm">
            <li>✓ Only masked text is sent: the PII guard blocks any payload that still matches an identifier.</li>
            <li>✓ data_collection = deny: providers that train on or store prompts are excluded.</li>
            <li>✓ Zero data retention endpoints only.</li>
            <li>✓ Tickets flagged by the injection screen are never sent.</li>
          </ul>
          <p className="mt-2 text-xs text-text-muted">{cfg.data.status.privacy?.note}</p>
          <p className="mt-1 text-xs text-text-muted">{cfg.data.credentials}</p>
        </Card>
        <Card title="OpenRouter account (as reported for this key)">
          {!canManage ? (
            <p className="text-sm text-text-muted">Visible to administrators.</p>
          ) : account.isLoading ? (
            <Spinner label="Loading" />
          ) : account.data ? (
            <div className="grid grid-cols-2 gap-2">
              <Mini label="Used today" value={formatUsd(account.data.usage_daily_usd)} />
              <Mini label="Used this month" value={formatUsd(account.data.usage_monthly_usd)} />
              <Mini label="Used in total" value={formatUsd(account.data.usage_usd)} />
              <Mini label="Key limit remaining" value={account.data.limit_remaining_usd === null ? "no limit set" : formatUsd(account.data.limit_remaining_usd)} />
            </div>
          ) : (
            <p className="text-sm text-text-muted">
              {account.error instanceof ApiError ? account.error.message : "Not available until a key is configured."}
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function AiManagementPage() {
  const { data: user } = useCurrentUser();
  const [tab, setTab] = useState<Tab>("overview");
  if (user && !hasPermission(user, "ai:read")) return <Alert tone="danger">Your role cannot view AI management.</Alert>;
  const tabs: [Tab, string][] = [
    ["overview", "Overview"],
    ["calls", "Call log"],
    ["config", "Models and limits"],
  ];
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">AI management</h1>
        <p className="text-sm text-text-muted">
          What the AI costs per ticket, how it behaves, and how it is configured. Every figure comes from recorded model calls,
          priced with the cost the provider reports.
        </p>
      </div>
      <div role="tablist" aria-label="AI management" className="flex gap-1 border-b border-border">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === key ? "border-accent font-medium text-text" : "border-transparent text-text-muted hover:text-text"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "calls" && <Calls />}
      {tab === "config" && <Config />}
    </div>
  );
}
