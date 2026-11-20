"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst, humanize } from "@/lib/format";
import type { ApprovalDetail, ApprovalSummary, Page } from "@/types/api";

const RULE_LABELS: Record<string, string> = {
  R1: "Blocked: instructions to AI",
  R2: "Customer not verified",
  R5: "No category / low confidence",
  R6: "P1 pay or billing",
  R7: "Statutory answer",
};

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : "Request failed";
}

function ReviewPanel({ id }: { id: string }) {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const key = ["approval", id];
  const detail = useQuery<ApprovalDetail>({ queryKey: key, queryFn: () => apiFetch(`/api/v1/approvals/${id}`) });
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [target, setTarget] = useState("L2");
  const [queue, setQueue] = useState("");

  useEffect(() => {
    setDraft(detail.data?.draft_text ?? "");
  }, [detail.data?.id, detail.data?.draft_text]);

  const onDone = (data: ApprovalDetail) => {
    queryClient.setQueryData(key, data);
    queryClient.invalidateQueries({ queryKey: ["approvals"] });
  };
  const save = useMutation({
    mutationFn: () => apiFetch<ApprovalDetail>(`/api/v1/approvals/${id}/draft`, { method: "PUT", body: JSON.stringify({ text: draft }) }),
    onSuccess: onDone,
  });
  const act = useMutation({
    mutationFn: (body: { action: string; note?: string; target?: string }) =>
      apiFetch<ApprovalDetail>(`/api/v1/approvals/${id}/decision`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: onDone,
    onError: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  if (detail.isLoading) return <Spinner />;
  if (!detail.data) return <Alert tone="danger">Could not load this review item.</Alert>;
  const a = detail.data;
  const e = a.evidence;
  const pending = a.status === "pending";
  const canEdit = pending && hasPermission(user, "approvals:edit");
  const canDecide = pending && hasPermission(user, "approvals:decide");
  const dirty = draft !== (a.draft_text ?? "");

  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/tickets/${a.ticket_external_id ?? a.ticket_id}`} className="font-mono text-accent hover:underline">
            {a.ticket_external_id}
          </Link>
          <Badge tone={a.lane === "block" ? "danger" : "neutral"}>{humanize(a.lane)}</Badge>
          <Badge>{a.queue}</Badge>
          <Badge tone={a.status === "pending" ? "neutral" : "success"}>{a.status}</Badge>
          {a.requires_second_person && <Badge>two-person rule</Badge>}
        </div>
        <p className="mt-2">{e.summary}</p>
        <p className="mt-1 text-text-muted">
          Why a person: {a.escalation_reason} (rule {a.rule_id})
        </p>
      </div>

      {e.injection_signals.length > 0 && (
        <Alert tone="danger">Instruction-like text found: “{e.injection_signals.join("”, “")}”. Treat the ticket as untrusted.</Alert>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md bg-surface-muted p-3">
          <p className="mb-1 text-xs text-text-muted">Customer and SLA</p>
          <p>{e.customer ? `${e.customer.name} · ${e.customer.tier} · ${e.customer.region}` : "Customer not verified"}</p>
          {e.sla && e.sla.applicable ? (
            <p>
              Resolution target {String(e.sla.resolution_target_h)} h · {e.sla.resolution_breached ? "breached" : "met / open"}
              {e.sla.credit_usd ? ` · credit USD ${e.sla.credit_usd}` : ""}
            </p>
          ) : (
            <p className="text-text-muted">SLA: {humanize(String(e.sla?.not_applicable_reason ?? "not applicable"))}</p>
          )}
          {e.incidents.map((i, n) => (
            <p key={n} className="text-xs">
              {i.kind} ({i.role}) · owner {i.owner_queue}
            </p>
          ))}
        </div>
        <div className="rounded-md bg-surface-muted p-3">
          <p className="mb-1 text-xs text-text-muted">Statutory values in force on {e.ticket.ticket_date}</p>
          {e.statutory_rates_in_force.length === 0 ? (
            <p className="text-text-muted">None for this region.</p>
          ) : (
            e.statutory_rates_in_force.map((r) => (
              <p key={r.rule_id}>
                <span className="font-mono text-xs">{r.rule_id}</span>: {r.value}
              </p>
            ))
          )}
        </div>
      </div>

      <div>
        <p className="mb-1 text-xs text-text-muted">Knowledge in force on the ticket date</p>
        {e.knowledge_in_force.length === 0 ? (
          <p className="text-text-muted">Nothing relevant in force: insufficient evidence.</p>
        ) : (
          <ul className="space-y-1">
            {e.knowledge_in_force.map((k) => (
              <li key={`${k.document_id}-${k.version}`}>
                <span className="font-mono text-xs">
                  {k.document_id} v{k.version}
                </span>{" "}
                {k.title} {!k.content_complete && <Badge>title only</Badge>}
                <span className="text-xs text-text-muted">
                  {" "}
                  ({k.effective_from ?? "…"} → {k.effective_to ?? "in force"})
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2">
        <label htmlFor="draft" className="text-xs text-text-muted">
          Reply draft. Use tokens such as {e.pii_tokens[0] ?? "<PAN_1>"} for personal data; never paste raw values. {e.suggested_response_note}
        </label>
        <textarea
          id="draft"
          value={draft}
          onChange={(ev) => setDraft(ev.target.value)}
          readOnly={!canEdit}
          rows={5}
          className="w-full rounded-md border border-border bg-surface p-2 text-sm"
        />
        {canEdit && (
          <Button variant="secondary" onClick={() => save.mutate()} disabled={save.isPending || !draft.trim() || !dirty}>
            {save.isPending ? "Validating…" : "Save and validate"}
          </Button>
        )}
        {save.isError && <Alert tone="danger">{errorText(save.error)}</Alert>}
        {a.validation && (
          <ul className="space-y-1 rounded-md border border-border p-2">
            <li className="font-medium">{a.validation.passed ? "All checks passed" : "Validation failed"}</li>
            {a.validation.checks.map((c) => (
              <li key={c.name} className="flex flex-wrap gap-2 text-xs">
                <Badge tone={c.passed ? "success" : "danger"}>{c.passed ? "pass" : "fail"}</Badge>
                <span className="font-mono">{c.name}</span>
                <span className="text-text-muted">{c.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {canDecide && (
        <div className="space-y-2 border-t border-border pt-3">
          <Input placeholder="Note (required to resolve)" value={note} onChange={(ev) => setNote(ev.target.value)} aria-label="Decision note" />
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => act.mutate({ action: "approve", note })} disabled={act.isPending || dirty || !a.validation?.passed || a.lane === "block"}>
              Approve reply
            </Button>
            <Button variant="secondary" onClick={() => act.mutate({ action: "reject", note })} disabled={act.isPending}>
              Reject draft
            </Button>
            <Button variant="secondary" onClick={() => act.mutate({ action: "resolve", note })} disabled={act.isPending || !note.trim()}>
              Resolve without reply
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={target} onChange={(ev) => setTarget(ev.target.value)} aria-label="Escalation target" className="rounded-md border border-border bg-surface px-2 py-2 text-sm">
              <option value="L2">L2 specialist</option>
              <option value="L3">L3 engineering</option>
              <option value="SECURITY">Security</option>
              <option value="DPO">DPO</option>
            </select>
            <Button variant="secondary" onClick={() => act.mutate({ action: "escalate", target, note })} disabled={act.isPending}>
              Escalate
            </Button>
            <Input placeholder="Queue, e.g. Payroll-Ops" value={queue} onChange={(ev) => setQueue(ev.target.value)} className="max-w-48" aria-label="Reassign to queue" />
            <Button variant="secondary" onClick={() => act.mutate({ action: "reassign", target: queue, note })} disabled={act.isPending || !queue.trim()}>
              Reassign
            </Button>
          </div>
          {dirty && <p className="text-xs text-text-muted">Save the draft before approving.</p>}
          {act.isError && <Alert tone="danger">{errorText(act.error)}</Alert>}
        </div>
      )}

      <div>
        <p className="mb-1 text-xs text-text-muted">History</p>
        <ol className="space-y-1 text-xs">
          {a.events.map((ev, n) => (
            <li key={n}>
              {formatIst(ev.occurred_at)} · {ev.action} → {ev.to_status}
              {ev.note ? ` · ${ev.note}` : ""}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const { data: user } = useCurrentUser();
  const [status, setStatus] = useState("pending");
  const [rule, setRule] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery<Page<ApprovalSummary>>({
    queryKey: ["approvals", status, rule, page],
    queryFn: () => apiFetch(`/api/v1/approvals?status=${status}&page=${page}&page_size=25${rule ? `&rule_id=${rule}` : ""}`),
    enabled: hasPermission(user, "approvals:read"),
    placeholderData: keepPreviousData,
  });

  if (!hasPermission(user, "approvals:read")) return <Alert tone="danger">You do not have permission to view the review queue.</Alert>;
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / 25)) : 1;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Review queue</h1>
        <p className="text-sm text-text-muted">
          Tickets the routing rules sent to a person. Replies can only be approved after every validation check passes; nothing here moves money.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <select value={status} onChange={(ev) => { setStatus(ev.target.value); setPage(1); }} aria-label="Status" className="rounded-md border border-border bg-surface px-2 py-2 text-sm">
          {["pending", "approved", "rejected", "escalated", "resolved", "all"].map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </select>
        <select value={rule} onChange={(ev) => { setRule(ev.target.value); setPage(1); }} aria-label="Reason" className="rounded-md border border-border bg-surface px-2 py-2 text-sm">
          <option value="">All reasons</option>
          {Object.entries(RULE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <Card title={`Items (${list.data?.total ?? 0})`} className="xl:col-span-2">
          {list.isLoading ? (
            <Spinner />
          ) : list.data?.total === 0 ? (
            <p className="text-sm text-text-muted">Nothing waiting. Items appear when routing sends a ticket to a person.</p>
          ) : (
            <ul className="divide-y divide-border text-sm">
              {list.data?.items.map((a) => (
                <li key={a.id}>
                  <button type="button" onClick={() => setSelected(a.id)} className={`w-full px-2 py-2 text-left hover:bg-surface-muted ${selected === a.id ? "bg-surface-muted" : ""}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs">{a.ticket_external_id}</span>
                      <Badge tone={a.lane === "block" ? "danger" : "neutral"}>{RULE_LABELS[a.rule_id] ?? a.rule_id}</Badge>
                      {a.sla_breached && <Badge tone="danger">SLA breached</Badge>}
                      {a.validation_passed === true && <Badge tone="success">draft valid</Badge>}
                      {a.validation_passed === false && <Badge tone="danger">draft invalid</Badge>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-text-muted">{a.summary}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex items-center gap-2 text-sm">
            <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span className="text-text-muted">
              {page} / {totalPages}
            </span>
            <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        </Card>
        <Card title="Review" className="xl:col-span-3">
          {selected ? <ReviewPanel id={selected} /> : <p className="text-sm text-text-muted">Select an item to review.</p>}
        </Card>
      </div>
    </div>
  );
}
