"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Alert, Badge, Card, Spinner } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatIst } from "@/lib/format";
import type { Customer, Incident, Page, TicketSummary } from "@/types/api";

interface CustomerDetail extends Customer {
  sla_terms: { tier: string; priority: string; first_response_h: string; resolution_h: string; credit_pct: string; source: string }[];
}

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const customer = useQuery<CustomerDetail>({ queryKey: ["customer", id], queryFn: () => apiFetch(`/api/v1/customers/${id}`), retry: false });
  const tickets = useQuery<Page<TicketSummary>>({
    queryKey: ["customer-tickets", id],
    queryFn: () => apiFetch(`/api/v1/tickets?customer_id=${id}&page_size=10`),
  });
  const cases = useQuery<Page<Incident>>({
    queryKey: ["customer-cases", id],
    queryFn: () => apiFetch(`/api/v1/duplicates?customer_id=${id}&page_size=20`),
  });

  if (customer.isLoading) return <Spinner />;
  if (!customer.data) return <Alert tone="danger">Customer not found, or outside your region scope.</Alert>;
  const c = customer.data;

  return (
    <div className="space-y-4">
      <div>
        <Link href="/customers" className="text-sm text-accent hover:underline">
          ← Customers
        </Link>
        <h1 className="mt-1 text-xl font-semibold">{c.name}</h1>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge>{c.customer_id}</Badge>
          <Badge>{c.tier}</Badge>
          <Badge>{c.region}</Badge>
          <Badge>USD {Number(c.monthly_fee_usd).toLocaleString()} / month</Badge>
          {c.employees_paid && <Badge>{c.employees_paid.toLocaleString()} employees paid</Badge>}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Exposure (ingested tickets)">
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between"><dt className="text-text-muted">Tickets</dt><dd>{c.ticket_count}</dd></div>
            <div className="flex justify-between"><dt className="text-text-muted">SLA breaches</dt><dd>{c.sla_breaches}</dd></div>
            <div className="flex justify-between"><dt className="text-text-muted">Credits</dt><dd>USD {Number(c.credits_usd).toFixed(2)}</dd></div>
          </dl>
        </Card>
        <Card title="Contract SLA (Schedule 3, v3.2)" className="lg:col-span-2">
          {c.sla_terms.length === 0 ? (
            <p className="text-sm text-text-muted">{c.tier} tier: best effort, no service credits.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Priority</th>
                  <th className="py-1 pr-3 font-medium">First response</th>
                  <th className="py-1 pr-3 font-medium">Resolution</th>
                  <th className="py-1 font-medium">Credit if missed</th>
                </tr>
              </thead>
              <tbody>
                {c.sla_terms.map((t) => (
                  <tr key={t.priority} className="border-t border-border tabular-nums">
                    <td className="py-1 pr-3">{t.priority}</td>
                    <td className="py-1 pr-3">{Number(t.first_response_h)} h</td>
                    <td className="py-1 pr-3">{Number(t.resolution_h)} h</td>
                    <td className="py-1">{Number(t.credit_pct)}% (×1.5 beyond twice the target)</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      <Card title={`Recent tickets (${tickets.data?.total ?? 0})`}>
        <ul className="divide-y divide-border text-sm">
          {tickets.data?.items.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-2 py-2">
              <Link href={`/tickets/${t.external_id ?? t.id}`} className="font-mono text-xs text-accent hover:underline">
                {t.external_id}
              </Link>
              <span>{t.subject_redacted ?? "—"}</span>
              <span className="text-xs text-text-muted">{formatIst(t.created_at)}</span>
              {t.sla_resolution_breached && <Badge tone="danger">SLA breach</Badge>}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-text-muted">Showing the 10 most recent.</p>
      </Card>
      <Card title={`Grouped cases (${cases.data?.total ?? 0})`}>
        {cases.data?.items.length ? (
          <ul className="space-y-1 text-sm">
            {cases.data.items.map((i) => (
              <li key={i.id}>
                {i.kind} · {i.ticket_count} tickets · master {i.master_external_id} · declared {formatIst(i.declared_at)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-text-muted">No resubmissions or incidents for this customer.</p>
        )}
      </Card>
    </div>
  );
}
