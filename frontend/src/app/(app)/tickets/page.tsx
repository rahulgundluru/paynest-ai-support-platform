"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Alert, Badge, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { apiFetch } from "@/lib/api";
import { CATEGORY_LABELS, CHANNEL_LABELS, formatIst, humanize } from "@/lib/format";
import type { Page, TicketSummary } from "@/types/api";

const PAGE_SIZE = 25;

interface Filters {
  q: string;
  channel: string;
  priority: string;
  category: string;
  region: string;
  ingestion_status: string;
  sla_breached: string;
  payroll_window: string;
  reassigned: string;
}

const EMPTY: Filters = {
  q: "",
  channel: "",
  priority: "",
  category: "",
  region: "",
  ingestion_status: "",
  sla_breached: "",
  payroll_window: "",
  reassigned: "",
};

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  const id = `f-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs text-text-muted">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-surface px-2 py-2 text-sm"
      >
        <option value="">All</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </div>
  );
}

export default function TicketsPage() {
  const { data: user } = useCurrentUser();
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  const allowed = hasPermission(user, "tickets:read");

  const query = useQuery<Page<TicketSummary>>({
    queryKey: ["tickets", filters, page, order],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), order });
      for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
      return apiFetch(`/api/v1/tickets?${params}`);
    },
    enabled: allowed,
    placeholderData: keepPreviousData,
  });

  if (!allowed) return <Alert tone="danger">You do not have permission to view tickets.</Alert>;
  const set = (key: keyof Filters) => (value: string) => setDraft((d) => ({ ...d, [key]: value }));
  const totalPages = query.data ? Math.max(1, Math.ceil(query.data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Tickets</h1>
        <p className="text-sm text-text-muted">
          Ingested tickets from email, widget, partner portal, WhatsApp and phone. Text is shown redacted.
        </p>
      </div>
      <Card>
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setFilters(draft);
          }}
        >
          <div className="space-y-1 sm:col-span-2 lg:col-span-1">
            <label htmlFor="f-q" className="text-xs text-text-muted">
              Search
            </label>
            <Input id="f-q" placeholder="PN-100724 or subject text" value={draft.q} onChange={(e) => set("q")(e.target.value)} />
          </div>
          <Select label="Channel" value={draft.channel} onChange={set("channel")} options={Object.entries(CHANNEL_LABELS)} />
          <Select label="Priority" value={draft.priority} onChange={set("priority")} options={[["P1", "P1"], ["P2", "P2"], ["P3", "P3"]]} />
          <Select label="Customer's category" value={draft.category} onChange={set("category")} options={Object.entries(CATEGORY_LABELS)} />
          <Select label="Region" value={draft.region} onChange={set("region")} options={[["IN", "India"], ["UAE", "UAE"]]} />
          <Select
            label="Ingestion status"
            value={draft.ingestion_status}
            onChange={set("ingestion_status")}
            options={[["processed", "Processed"], ["requires_review", "Requires review"]]}
          />
          <Select label="SLA breached" value={draft.sla_breached} onChange={set("sla_breached")} options={[["true", "Yes"], ["false", "No"]]} />
          <Select label="Payroll window" value={draft.payroll_window} onChange={set("payroll_window")} options={[["true", "25th–3rd"], ["false", "Outside"]]} />
          <Select label="Changed queue" value={draft.reassigned} onChange={set("reassigned")} options={[["true", "Yes"], ["false", "No"]]} />
          <div className="flex items-end gap-2">
            <Button type="submit">Apply</Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setDraft(EMPTY);
                setFilters(EMPTY);
                setPage(1);
              }}
            >
              Reset
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        {query.isLoading ? (
          <Spinner />
        ) : query.isError ? (
          <Alert tone="danger">Could not load tickets.</Alert>
        ) : query.data?.total === 0 ? (
          <p className="text-sm text-text-muted">
            No tickets match. If nothing has been ingested yet, a support lead or admin can run ingestion from the
            Data ingestion page.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-2 pr-3 font-medium">Ticket</th>
                  <th className="py-2 pr-3 font-medium">Subject (redacted)</th>
                  <th className="py-2 pr-3 font-medium">Customer</th>
                  <th className="py-2 pr-3 font-medium">Channel</th>
                  <th className="py-2 pr-3 font-medium">Prio</th>
                  <th className="py-2 pr-3 font-medium">Final queue</th>
                  <th className="py-2 pr-3 font-medium">
                    <button type="button" className="font-medium underline-offset-2 hover:underline" onClick={() => setOrder((o) => (o === "desc" ? "asc" : "desc"))}>
                      Created {order === "desc" ? "↓" : "↑"}
                    </button>
                  </th>
                  <th className="py-2 font-medium">Flags</th>
                </tr>
              </thead>
              <tbody>
                {query.data?.items.map((t) => (
                  <tr key={t.id} className="border-t border-border align-top">
                    <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">
                      <Link className="text-accent hover:underline" href={`/tickets/${t.external_id ?? t.id}`}>
                        {t.external_id ?? "(no id)"}
                      </Link>
                    </td>
                    <td className="max-w-xs py-2 pr-3">{t.subject_redacted ?? <span className="text-text-muted">—</span>}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">
                      {t.customer_name ?? <span className="text-text-muted">unresolved</span>}
                      <div className="text-xs text-text-muted">
                        {t.customer_tier ?? ""} {t.region ? `· ${t.region}` : ""}
                      </div>
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap">{CHANNEL_LABELS[t.channel] ?? t.channel}</td>
                    <td className="py-2 pr-3">{t.priority ?? "—"}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">{t.final_queue ?? "—"}</td>
                    <td className="py-2 pr-3 whitespace-nowrap text-xs">{formatIst(t.created_at)}</td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1">
                        {t.sla_resolution_breached && <Badge tone="danger">SLA breach</Badge>}
                        {t.reassignment_count > 0 && <Badge>{t.reassignment_count}× moved</Badge>}
                        {t.pii_entity_count > 0 && <Badge>PII ×{t.pii_entity_count}</Badge>}
                        {t.ingestion_status === "requires_review" && <Badge tone="danger">{humanize(t.ingestion_status)}</Badge>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </Button>
        <span className="text-text-muted">
          Page {page} of {totalPages} · {query.data?.total ?? 0} tickets
        </span>
        <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
