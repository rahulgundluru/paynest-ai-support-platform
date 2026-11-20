"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PipelineFlow } from "@/components/pipeline-flow";
import { Alert, Button, Card, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst } from "@/lib/format";
import type { TicketDetail } from "@/types/api";
import { formatUsd, type PipelineRun } from "@/types/pipeline";

function FlowView() {
  const { ref } = useParams<{ ref: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: user } = useCurrentUser();
  const canRun = hasPermission(user, "tickets:process");

  const ticket = useQuery<TicketDetail>({
    queryKey: ["ticket", ref],
    queryFn: () => apiFetch(`/api/v1/tickets/${encodeURIComponent(ref)}`),
    retry: false,
  });
  const runs = useQuery<PipelineRun[]>({
    queryKey: ["pipeline-runs", ref],
    queryFn: () => apiFetch(`/api/v1/tickets/${encodeURIComponent(ref)}/pipeline`),
  });
  const runId = params.get("run") ?? runs.data?.[0]?.id ?? null;
  const run = useQuery<PipelineRun>({
    queryKey: ["pipeline-run", runId],
    queryFn: () => apiFetch(`/api/v1/pipeline-runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 700 : false),
  });
  const rerun = useMutation({
    mutationFn: () => apiFetch<PipelineRun>(`/api/v1/tickets/${encodeURIComponent(ref)}/pipeline`, { method: "POST" }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs", ref] });
      router.replace(`/tickets/${ref}/flow?run=${r.id}`);
    },
  });

  if (ticket.isError) {
    const notFound = ticket.error instanceof ApiError && ticket.error.status === 404;
    return <Alert tone="danger">{notFound ? "Ticket not found, or it is outside your region scope." : "Could not load the ticket."}</Alert>;
  }
  const t = ticket.data;
  const current = run.data;
  const routing = current?.steps.find((s) => s.key === "routing");
  const draft = current?.steps.find((s) => s.key === "draft");
  const review = current?.steps.find((s) => s.key === "review");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href={`/tickets/${ref}`} className="text-sm text-accent hover:underline">
            ← Ticket {ref}
          </Link>
          <h1 className="mt-1 text-xl font-semibold">How this ticket was processed</h1>
          {t && (
            <p className="text-sm text-text-muted">
              <span className="font-mono">{t.external_id}</span> · {t.subject_redacted ?? "(no subject)"} · {t.customer_name ?? "unverified customer"}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(runs.data?.length ?? 0) > 1 && (
            <select
              aria-label="Pipeline run"
              className="rounded-md border border-border bg-surface px-2 py-2 text-sm"
              value={runId ?? ""}
              onChange={(e) => router.replace(`/tickets/${ref}/flow?run=${e.target.value}`)}
            >
              {runs.data!.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.trigger === "create" ? "Created" : "Re-run"} · {formatIst(r.started_at)} · {formatUsd(r.total_cost_usd)}
                </option>
              ))}
            </select>
          )}
          {canRun && (
            <Button
              variant="secondary"
              disabled={rerun.isPending || current?.status === "running"}
              onClick={() => rerun.mutate()}
            >
              {rerun.isPending ? "Starting…" : "Run the pipeline again"}
            </Button>
          )}
          <Link href="/review" className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-contrast hover:opacity-90">
            Review queue
          </Link>
        </div>
      </div>

      {rerun.isError && (
        <Alert tone="danger">{rerun.error instanceof ApiError ? rerun.error.message : "Could not start the pipeline."}</Alert>
      )}
      {(runs.isLoading || run.isLoading) && <Spinner label="Loading the pipeline run" />}
      {runs.data && runs.data.length === 0 && !runId && (
        <Card>
          <p className="text-sm text-text-muted">
            This ticket was processed by the batch import, so it has no recorded run yet.
            {canRun ? " Run the pipeline to see every step." : " A user with processing rights can run it."}
          </p>
        </Card>
      )}

      {current && (
        <>
          {current.status !== "running" && (
            <div className="grid gap-3 md:grid-cols-3">
              <Card>
                <p className="text-xs text-text-muted">Decision</p>
                <p className="mt-1 text-sm font-medium">{routing?.summary ?? "—"}</p>
              </Card>
              <Card>
                <p className="text-xs text-text-muted">Reply</p>
                <p className="mt-1 text-sm font-medium">{draft?.summary ?? "—"}</p>
              </Card>
              <Card>
                <p className="text-xs text-text-muted">Next</p>
                <p className="mt-1 text-sm font-medium">{review?.summary ?? "—"}</p>
              </Card>
            </div>
          )}
          <PipelineFlow run={current} />
        </>
      )}
    </div>
  );
}

export default function FlowPage() {
  return (
    <Suspense fallback={<Spinner label="Loading" />}>
      <FlowView />
    </Suspense>
  );
}
