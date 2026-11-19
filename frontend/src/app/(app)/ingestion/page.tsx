"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Alert, Badge, Button, Card, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst, humanize } from "@/lib/format";
import type { IngestionBatch, Page } from "@/types/api";

function Counts({ data }: { data?: Record<string, number> }) {
  if (!data || Object.keys(data).length === 0) return <span className="text-text-muted">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {Object.entries(data).map(([k, v]) => (
        <Badge key={k} tone={k === "failed" ? "danger" : "neutral"}>
          {humanize(k)}: {v}
        </Badge>
      ))}
    </div>
  );
}

export default function IngestionPage() {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const canRead = hasPermission(user, "ingestion:read");
  const canRun = hasPermission(user, "ingestion:run");

  const batches = useQuery<Page<IngestionBatch>>({
    queryKey: ["ingestion-batches"],
    queryFn: () => apiFetch("/api/v1/processing/batches?page_size=20"),
    enabled: canRead,
  });
  const run = useMutation({
    mutationFn: () => apiFetch<IngestionBatch>("/api/v1/processing/ingest", { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ingestion-batches"] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });

  if (!canRead) return <Alert tone="danger">You do not have permission to view ingestion runs.</Alert>;
  const latest = batches.data?.items[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Data ingestion</h1>
          <p className="text-sm text-text-muted">
            Ingests the pinned source exports. Re-running is safe: records already ingested are skipped.
          </p>
        </div>
        {canRun && (
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? "Ingesting…" : "Run ingestion"}
          </Button>
        )}
      </div>
      {run.isError && (
        <Alert tone="danger">
          Ingestion failed{run.error instanceof ApiError ? `: ${run.error.message}` : ""}.
        </Alert>
      )}
      {run.isSuccess && <Alert tone="success">Ingestion finished with status “{run.data.status}”.</Alert>}

      {batches.isLoading ? (
        <Spinner />
      ) : !latest ? (
        <Card>
          <p className="text-sm text-text-muted">No ingestion has run yet.</p>
        </Card>
      ) : (
        <>
          <Card title={`Latest run · ${formatIst(latest.started_at)}`}>
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-text-muted">Totals</dt>
                <dd><Counts data={latest.summary.totals} /></dd>
              </div>
              {Object.entries(latest.summary.sources ?? {}).map(([file, counts]) => (
                <div key={file}>
                  <dt className="font-mono text-xs text-text-muted">{file}</dt>
                  <dd><Counts data={counts} /></dd>
                </div>
              ))}
              <div>
                <dt className="text-text-muted">Review reasons</dt>
                <dd><Counts data={latest.summary.review_reasons} /></dd>
              </div>
              <div>
                <dt className="text-text-muted">PII entities redacted (all fields, incl. contact fields)</dt>
                <dd><Counts data={latest.summary.pii?.all_entities_incl_contact_fields} /></dd>
              </div>
              <div>
                <dt className="text-text-muted">Records with PII in message text, by source</dt>
                <dd><Counts data={latest.summary.pii?.records_with_pii_in_free_text} /></dd>
              </div>
              <div className="text-xs text-text-muted">
                Source commit <span className="font-mono">{latest.source_commit ?? "unknown"}</span> · status {latest.status}
              </div>
            </dl>
          </Card>
          <Card title="Run history">
            <ul className="divide-y divide-border text-sm">
              {batches.data?.items.map((b) => (
                <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>{formatIst(b.started_at)}</span>
                  <Counts data={b.summary.totals} />
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
