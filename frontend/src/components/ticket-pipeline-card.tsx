"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { PipelineRail, STATUS } from "@/components/pipeline-flow";
import { Alert, Button, Card } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst } from "@/lib/format";
import { formatMs, formatUsd, type PipelineRun, type TicketAiCost } from "@/types/pipeline";

export function TicketPipelineCard({ ticketRef }: { ticketRef: string }) {
  const router = useRouter();
  const { data: user } = useCurrentUser();
  const canRun = hasPermission(user, "tickets:process");
  const runs = useQuery<PipelineRun[]>({
    queryKey: ["pipeline-runs", ticketRef],
    queryFn: () => apiFetch(`/api/v1/tickets/${encodeURIComponent(ticketRef)}/pipeline`),
  });
  const cost = useQuery<TicketAiCost>({
    queryKey: ["ticket-ai-cost", ticketRef],
    queryFn: () => apiFetch(`/api/v1/ai/tickets/${encodeURIComponent(ticketRef)}/cost`),
  });
  const run = useMutation({
    mutationFn: () => apiFetch<PipelineRun>(`/api/v1/tickets/${encodeURIComponent(ticketRef)}/pipeline`, { method: "POST" }),
    onSuccess: (r) => router.push(`/tickets/${ticketRef}/flow?run=${r.id}`),
  });
  const latest = runs.data?.[0];

  return (
    <Card title="Pipeline and AI cost">
      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-3 md:col-span-2">
          {latest ? (
            <>
              <p className="text-xs text-text-muted">
                Latest run · {latest.trigger === "create" ? "on creation" : "re-run"} · {formatIst(latest.started_at)} ·{" "}
                <span className={latest.status === "failed" ? "text-danger" : ""}>{latest.status}</span>
              </p>
              <PipelineRail steps={latest.steps} />
              <ul className="grid gap-1 text-xs sm:grid-cols-2">
                {latest.steps
                  .filter((s) => ["classify", "routing", "draft", "review"].includes(s.key))
                  .map((s) => (
                    <li key={s.key}>
                      <span className="font-medium">{s.label}</span>{" "}
                      <span className={STATUS[s.status].text}>({STATUS[s.status].label.toLowerCase()})</span>:{" "}
                      <span className="text-text-muted">{s.summary ?? "—"}</span>
                    </li>
                  ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-text-muted">
              No recorded pipeline run. Imported tickets were processed in batch; run the pipeline to see every step and
              its cost.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {latest && (
              <Link
                href={`/tickets/${ticketRef}/flow?run=${latest.id}`}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:opacity-90"
              >
                View the flow
              </Link>
            )}
            {canRun && (
              <Button variant="secondary" disabled={run.isPending} onClick={() => run.mutate()}>
                {run.isPending ? "Starting…" : latest ? "Run again" : "Run the full pipeline"}
              </Button>
            )}
          </div>
          {run.isError && (
            <Alert tone="danger">{run.error instanceof ApiError ? run.error.message : "Could not start the pipeline."}</Alert>
          )}
        </div>
        <div className="rounded-md bg-surface-muted p-3">
          <p className="text-xs text-text-muted">AI cost of this ticket</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{formatUsd(cost.data?.total_cost_usd ?? 0)}</p>
          <p className="text-xs text-text-muted">{cost.data?.calls ?? 0} model call(s), cost as reported by the provider</p>
          {cost.data?.by_operation.map((o) => (
            <div key={o.operation} className="mt-2 flex justify-between text-xs">
              <span className="capitalize">{o.operation === "classify" ? "Classification" : o.operation === "draft" ? "Draft" : o.operation}</span>
              <span className="tabular-nums">
                {formatUsd(o.cost_usd)} · {o.input_tokens + o.output_tokens} tok · {formatMs(o.latency_ms)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
