"use client";

import { useQuery } from "@tanstack/react-query";

import { Alert, Badge, Card, Spinner } from "@/components/ui";
import { useCurrentUser } from "@/hooks/use-auth";
import type { ReadyResponse } from "@/types/api";

function useSystemStatus() {
  return useQuery<ReadyResponse>({
    queryKey: ["system", "ready"],
    queryFn: async () => (await fetch("/system/ready", { cache: "no-store" })).json(),
    refetchInterval: 30_000,
  });
}

export default function DashboardPage() {
  const { data: user } = useCurrentUser();
  const status = useSystemStatus();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Support operations dashboard</h1>
        <p className="text-sm text-text-muted">Signed in as {user?.email}</p>
      </div>

      <Card title="Operational metrics">
        <Alert tone="warning">
          Dashboard metrics and charts are built in Phase 5 from the ingested data. Until then, use the Tickets and
          Data ingestion pages; no metric on this page is estimated or pre-filled.
        </Alert>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="System status">
          {status.isLoading ? (
            <Spinner />
          ) : (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-text-muted">Overall</dt>
                <dd>
                  <Badge tone={status.data?.status === "ok" ? "success" : "danger"}>{status.data?.status ?? "unknown"}</Badge>
                </dd>
              </div>
              {Object.entries(status.data?.checks ?? {}).map(([name, value]) => (
                <div key={name} className="flex justify-between">
                  <dt className="text-text-muted">{name}</dt>
                  <dd className="font-mono text-xs">{value ?? "—"}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
        <Card title="Your access">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-text-muted">Roles</dt>
              <dd className="text-right">{user?.roles.join(", ")}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-text-muted">Regions</dt>
              <dd>{user?.regions.join(", ")}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-text-muted">Permissions</dt>
              <dd className="text-right">{user?.permissions.length ? user.permissions.join(", ") : "none"}</dd>
            </div>
          </dl>
        </Card>
      </div>
    </div>
  );
}
