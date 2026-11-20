"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst, humanize } from "@/lib/format";

interface Run {
  id: string;
  gate: string;
  name: string;
  status: "pass" | "fail" | "partial" | "not_run";
  dataset: string;
  dataset_size: number;
  target: Record<string, unknown>;
  metrics: Record<string, unknown>;
  notes: string[];
  critical: boolean;
  started_at: string;
  finished_at: string | null;
}
interface GateRow {
  gate: string;
  latest: Run | null;
  failed_cases: number;
  history: { id: string; status: string; started_at: string }[];
}
interface RunDetail extends Run {
  cases: { case_id: string; passed: boolean; detail: Record<string, unknown> }[];
}

const STATUS_TONE: Record<string, "success" | "danger" | "neutral"> = { pass: "success", fail: "danger", partial: "neutral", not_run: "neutral" };
const STATUS_LABEL: Record<string, string> = { pass: "Pass", fail: "Fail", partial: "Partial", not_run: "Not run" };

function value(v: unknown): string {
  if (v === null || v === undefined) return "not measured";
  if (typeof v === "object") return Array.isArray(v) ? (v.length ? v.join(", ") : "none") : JSON.stringify(v);
  return String(v);
}

function RunPanel({ id }: { id: string }) {
  const detail = useQuery<RunDetail>({ queryKey: ["evaluation", id], queryFn: () => apiFetch(`/api/v1/evaluations/${id}`) });
  if (detail.isLoading || !detail.data) return <Spinner />;
  const r = detail.data;
  const failed = r.cases.filter((c) => !c.passed);
  return (
    <div className="space-y-3 text-sm">
      <p>
        <span className="font-medium">{r.gate}</span> · {r.name}
      </p>
      <p className="text-text-muted">
        Dataset: {r.dataset} ({r.dataset_size}) · run {formatIst(r.started_at)}
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-1 text-xs text-text-muted">Target</p>
          <dl className="space-y-1">
            {Object.entries(r.target).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <dt>{humanize(k)}</dt>
                <dd className="font-mono text-xs">{value(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div>
          <p className="mb-1 text-xs text-text-muted">Measured</p>
          <dl className="space-y-1">
            {Object.entries(r.metrics).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <dt>{humanize(k)}</dt>
                <dd className={`text-right font-mono text-xs ${v === null ? "text-text-muted" : ""}`}>{value(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
      {r.notes.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-xs text-text-muted">
          {r.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <div>
        <p className="mb-1 text-xs text-text-muted">
          Cases: {r.cases.length} · failed {failed.length}
        </p>
        {failed.length > 0 && (
          <ul className="max-h-60 space-y-1 overflow-auto text-xs">
            {failed.map((c) => (
              <li key={c.case_id} className="rounded border border-border p-2">
                <span className="font-mono">{c.case_id}</span> <span className="text-text-muted">{JSON.stringify(c.detail)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function EvaluationsPage() {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const canRead = hasPermission(user, "evaluations:read");
  const canRun = hasPermission(user, "evaluations:run");
  const [selected, setSelected] = useState<string | null>(null);
  const gates = useQuery<GateRow[]>({ queryKey: ["evaluation-gates"], queryFn: () => apiFetch("/api/v1/evaluations/gates"), enabled: canRead });
  const run = useMutation({
    mutationFn: () => apiFetch<Run[]>("/api/v1/evaluations/run", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["evaluation-gates"] }),
  });

  if (!canRead) return <Alert tone="danger">You do not have permission to view evaluations.</Alert>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Evaluations (G1–G7)</h1>
          <p className="text-sm text-text-muted">
            Results of executed runs only. Parts that need an AI model are shown as not run, never estimated.
          </p>
        </div>
        {canRun && (
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? "Running all gates (about a minute)…" : "Run all gates"}
          </Button>
        )}
      </div>
      {run.isError && <Alert tone="danger">Run failed{run.error instanceof ApiError ? `: ${run.error.message}` : ""}.</Alert>}
      <Card>
        {gates.isLoading ? (
          <Spinner />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-2 pr-3 font-medium">Gate</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Dataset</th>
                  <th className="py-2 pr-3 font-medium">Failed cases</th>
                  <th className="py-2 pr-3 font-medium">Last run</th>
                  <th className="py-2 font-medium">History (newest first)</th>
                </tr>
              </thead>
              <tbody>
                {gates.data?.map((g) => (
                  <tr key={g.gate} className={`border-t border-border align-top ${selected && g.latest?.id === selected ? "bg-surface-muted" : ""}`}>
                    <td className="py-2 pr-3">
                      {g.latest ? (
                        <button type="button" className="text-left text-accent hover:underline" onClick={() => setSelected(g.latest!.id)}>
                          <span className="font-medium">{g.gate}</span> {g.latest.name}
                        </button>
                      ) : (
                        <span className="font-medium">{g.gate}</span>
                      )}
                      {g.latest?.critical && <span className="ml-1 text-xs text-text-muted">(blocks the build)</span>}
                    </td>
                    <td className="py-2 pr-3">
                      {g.latest ? <Badge tone={STATUS_TONE[g.latest.status]}>{STATUS_LABEL[g.latest.status]}</Badge> : <Badge>Never run</Badge>}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{g.latest?.dataset_size ?? "—"}</td>
                    <td className="py-2 pr-3 tabular-nums">{g.latest ? g.failed_cases : "—"}</td>
                    <td className="py-2 pr-3 whitespace-nowrap text-xs">{g.latest ? formatIst(g.latest.started_at) : "—"}</td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1">
                        {g.history.map((h) => (
                          <button key={h.id} type="button" onClick={() => setSelected(h.id)} title={formatIst(h.started_at)}>
                            <Badge tone={STATUS_TONE[h.status]}>{STATUS_LABEL[h.status]}</Badge>
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Run detail">{selected ? <RunPanel id={selected} /> : <p className="text-sm text-text-muted">Select a gate or a history entry.</p>}</Card>
    </div>
  );
}
