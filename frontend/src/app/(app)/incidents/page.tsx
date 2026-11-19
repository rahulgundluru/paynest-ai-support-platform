"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Alert, Badge, Button, Card, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { CHANNEL_LABELS, formatIst, humanize } from "@/lib/format";
import type { Incident, IncidentDetail, Page } from "@/types/api";

function minutesBetween(a: string, b: string) {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);
}

function IncidentPanel({ id, canManage }: { id: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const detail = useQuery<IncidentDetail>({ queryKey: ["incident", id], queryFn: () => apiFetch(`/api/v1/duplicates/${id}`) });
  const unlink = useMutation({
    mutationFn: (ticketRef: string) =>
      apiFetch<IncidentDetail>(`/api/v1/duplicates/${id}/unlink`, { method: "POST", body: JSON.stringify({ ticket_ref: ticketRef }) }),
    onSuccess: (data) => {
      queryClient.setQueryData(["incident", id], data);
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
  if (detail.isLoading) return <Spinner />;
  if (!detail.data) return <Alert tone="danger">Could not load this case.</Alert>;
  const d = detail.data;
  return (
    <div className="space-y-3 text-sm">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
        <dt className="text-text-muted">Customer</dt>
        <dd>{d.customer_name ?? d.customer_id}</dd>
        <dt className="text-text-muted">Owner queue</dt>
        <dd>{d.owner_queue ?? "—"}</dd>
        <dt className="text-text-muted">First ticket</dt>
        <dd>{formatIst(d.first_ticket_at)}</dd>
        <dt className="text-text-muted">Declared</dt>
        <dd>
          {formatIst(d.declared_at)} ({minutesBetween(d.first_ticket_at, d.declared_at)} min later)
        </dd>
        <dt className="text-text-muted">Rule</dt>
        <dd className="font-mono text-xs">{d.rule_id}</dd>
      </dl>
      {unlink.isError && (
        <Alert tone="danger">Unlink failed{unlink.error instanceof ApiError ? `: ${unlink.error.message}` : ""}.</Alert>
      )}
      <ol className="space-y-2">
        {d.links.map((l) => (
          <li key={l.ticket_id} className={`rounded-md border border-border p-2 ${l.active ? "" : "opacity-50"}`}>
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/tickets/${l.external_id ?? l.ticket_id}`} className="font-mono text-xs text-accent hover:underline">
                {l.external_id}
              </Link>
              <Badge>{l.role}</Badge>
              <Badge>{CHANNEL_LABELS[l.channel] ?? l.channel}</Badge>
              {l.role === "resubmit" && l.confidence < 0.9 && (
                <Badge tone="danger">confirm original: {Math.round(l.confidence * 100)}%</Badge>
              )}
              {l.manual && <Badge>manual</Badge>}
              {!l.active && <Badge tone="danger">unlinked</Badge>}
              <span className="text-xs text-text-muted">{formatIst(l.created_at)}</span>
              {canManage && l.active && l.role !== "master" && (
                <Button variant="secondary" className="ml-auto px-2 py-1 text-xs" disabled={unlink.isPending} onClick={() => unlink.mutate(l.external_id ?? l.ticket_id)}>
                  Unlink
                </Button>
              )}
            </div>
            <p className="mt-1">{l.subject_redacted ?? "—"}</p>
            <p className="text-xs text-text-muted">{l.reason}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function IncidentsPage() {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<"" | "incident" | "resubmission">("incident");
  const [selected, setSelected] = useState<string | null>(null);
  const canManage = hasPermission(user, "incidents:manage");
  const list = useQuery<Page<Incident>>({
    queryKey: ["incidents", kind],
    queryFn: () => apiFetch(`/api/v1/duplicates?page_size=100${kind ? `&kind=${kind}` : ""}`),
    enabled: hasPermission(user, "tickets:read"),
    placeholderData: keepPreviousData,
  });
  const detect = useMutation({
    mutationFn: () => apiFetch<Record<string, number>>("/api/v1/duplicates/detect", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["incidents"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Incidents & duplicates</h1>
          <p className="text-sm text-text-muted">
            One customer, one case. Tickets are grouped, never merged: each keeps its channel, messages and history.
          </p>
        </div>
        <div className="flex gap-2">
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} aria-label="Case type" className="rounded-md border border-border bg-surface px-2 py-2 text-sm">
            <option value="incident">Incidents</option>
            <option value="resubmission">Resubmissions</option>
            <option value="">All</option>
          </select>
          {canManage && (
            <Button variant="secondary" onClick={() => detect.mutate()} disabled={detect.isPending}>
              {detect.isPending ? "Detecting…" : "Re-run detection"}
            </Button>
          )}
        </div>
      </div>
      {detect.isSuccess && (
        <Alert tone="success">{Object.entries(detect.data).map(([k, v]) => `${humanize(k)} ${v}`).join(" · ")}</Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Cases (${list.data?.total ?? 0})`}>
          {list.isLoading ? (
            <Spinner />
          ) : list.data?.total === 0 ? (
            <p className="text-sm text-text-muted">No cases. Run detection after ingestion.</p>
          ) : (
            <ul className="divide-y divide-border text-sm">
              {list.data?.items.map((i) => (
                <li key={i.id}>
                  <button type="button" onClick={() => setSelected(i.id)} className={`w-full px-2 py-2 text-left hover:bg-surface-muted ${selected === i.id ? "bg-surface-muted" : ""}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{i.customer_name ?? i.customer_id}</span>
                      <Badge>{i.kind}</Badge>
                      <Badge>{i.ticket_count} tickets</Badge>
                      {i.category && <Badge>{humanize(i.category)}</Badge>}
                    </div>
                    <div className="text-xs text-text-muted">
                      master {i.master_external_id} · declared {formatIst(i.declared_at)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Case detail">
          {selected ? <IncidentPanel id={selected} canManage={canManage} /> : <p className="text-sm text-text-muted">Select a case.</p>}
        </Card>
      </div>
    </div>
  );
}
