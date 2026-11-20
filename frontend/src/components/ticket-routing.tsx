"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Alert, Badge, Button, Card, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { CATEGORY_LABELS, formatIst, humanize } from "@/lib/format";
import type { TicketRouting } from "@/types/api";

export function TicketRoutingCard({ ticketRef }: { ticketRef: string }) {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const key = ["ticket-routing", ticketRef];
  const routing = useQuery<TicketRouting>({
    queryKey: key,
    queryFn: () => apiFetch(`/api/v1/tickets/${encodeURIComponent(ticketRef)}/routing`),
  });
  const process = useMutation({
    mutationFn: () => apiFetch(`/api/v1/tickets/${encodeURIComponent(ticketRef)}/process`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  const c = routing.data?.classification;
  const r = routing.data?.routing;
  return (
    <Card title="AI classification and routing">
      {routing.isLoading ? (
        <Spinner />
      ) : (
        <div className="space-y-3 text-sm">
          {r ? (
            <div className="rounded-md bg-surface-muted p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={r.lane === "block" ? "danger" : "neutral"}>{humanize(r.lane)}</Badge>
                <span className="font-medium">{r.queue}</span>
                <span className="text-xs text-text-muted">{r.support_level}</span>
                {r.requires_approval && <Badge tone="danger">human approval</Badge>}
              </div>
              <p className="mt-1">{r.reason}</p>
              <p className="mt-1 text-xs text-text-muted">
                Rule <span className="font-mono">{r.rule_id}</span> · {r.rule_version} · decided {formatIst(r.decided_at)} · category from{" "}
                {humanize(String(r.inputs.category_source ?? "—"))}
              </p>
            </div>
          ) : (
            <p className="text-text-muted">No routing decision recorded yet.</p>
          )}

          {c && (
            <div>
              <p className="text-xs text-text-muted">
                Classifier: {c.provider} {c.model ?? ""} · prompt {c.prompt_version} · status{" "}
                <span className={c.status === "ok" ? "" : "text-danger"}>{c.status}</span>
              </p>
              {c.status === "ok" ? (
                <p>
                  {c.category ? CATEGORY_LABELS[c.category] : "—"} · {c.priority} · confidence {c.confidence?.toFixed(2)}
                  {c.requires_human ? " · needs a person" : ""}
                </p>
              ) : (
                <p className="text-text-muted">
                  {c.status === "unavailable"
                    ? "No AI model is configured yet, so nothing was guessed: the ticket goes to a person."
                    : `Classification did not complete (${c.error ?? "unknown"}); routed to a person.`}
                </p>
              )}
              {c.is_injection && <Alert tone="danger">Instructions aimed at an AI were found in this ticket. No automated action is taken.</Alert>}
            </div>
          )}

          {routing.data?.incidents.map((i) => (
            <p key={i.id} className="text-xs">
              Part of {i.kind} with {i.ticket_count} tickets (master {i.master_external_id}) · owner {i.owner_queue}
            </p>
          ))}

          {process.isError && (
            <Alert tone="danger">Processing failed{process.error instanceof ApiError ? `: ${process.error.message}` : ""}.</Alert>
          )}
          {hasPermission(user, "tickets:process") && (
            <Button variant="secondary" onClick={() => process.mutate()} disabled={process.isPending}>
              {process.isPending ? "Processing…" : "Run classification and routing"}
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
