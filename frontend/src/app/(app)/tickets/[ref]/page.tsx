"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { TicketRoutingCard } from "@/components/ticket-routing";
import { Alert, Badge, Card, Spinner } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import { CATEGORY_LABELS, CHANNEL_LABELS, formatIst, humanize } from "@/lib/format";
import type { TicketDetail } from "@/types/api";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

function YesNo({ value }: { value: boolean | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-text-muted">unknown</span>;
  return <Badge tone={value ? "danger" : "success"}>{value ? "breached" : "met"}</Badge>;
}

export default function TicketDetailPage() {
  const { ref } = useParams<{ ref: string }>();
  const query = useQuery<TicketDetail>({
    queryKey: ["ticket", ref],
    queryFn: () => apiFetch(`/api/v1/tickets/${encodeURIComponent(ref)}`),
    retry: false,
  });

  if (query.isLoading) return <Spinner label="Loading ticket" />;
  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return <Alert tone="danger">{notFound ? "Ticket not found, or it is outside your region scope." : "Could not load the ticket."}</Alert>;
  }
  const t = query.data!;
  const sla = t.sla;

  return (
    <div className="space-y-4">
      <div>
        <Link href="/tickets" className="text-sm text-accent hover:underline">
          ← Tickets
        </Link>
        <h1 className="mt-1 text-xl font-semibold">
          <span className="font-mono">{t.external_id ?? "(no ticket id)"}</span> · {t.subject_redacted ?? CHANNEL_LABELS[t.channel]}
        </h1>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge>{CHANNEL_LABELS[t.channel]}</Badge>
          {t.priority && <Badge>{t.priority}</Badge>}
          {t.in_payroll_window && <Badge>payroll window</Badge>}
          {t.ingestion_status === "requires_review" && <Badge tone="danger">requires review</Badge>}
          {t.review_reasons.map((r) => (
            <Badge key={r} tone="danger">
              {humanize(r)}
            </Badge>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Message (redacted)" className="lg:col-span-2">
          <p className="text-xs text-text-muted">
            Personal data was replaced with tokens before storage. Original values are held encrypted in the regional
            vault and are not available in this view.
          </p>
          <p className="mt-3 whitespace-pre-wrap text-sm">{t.body_redacted ?? "—"}</p>
          {t.messages.length > 1 && (
            <ol className="mt-4 space-y-2 border-t border-border pt-3">
              {t.messages.map((m) => (
                <li key={m.seq} className="text-sm">
                  <span className="text-xs text-text-muted">
                    {m.author_type} · {formatIst(m.sent_at)}
                  </span>
                  <p className="whitespace-pre-wrap">{m.body_redacted}</p>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card title="Customer">
          <dl>
            <Row label="Customer">{t.customer_name ?? "unresolved"}</Row>
            <Row label="Id">{t.customer_id ?? "—"}</Row>
            <Row label="Tier">{t.customer_tier ?? "—"}</Row>
            <Row label="Region">{t.region ?? "unknown"}</Row>
            <Row label="Resolved by">{humanize(t.customer_resolution)}</Row>
            {t.partner_id && <Row label="Partner">{t.partner_id}</Row>}
          </dl>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Queue history">
          <dl>
            <Row label="Customer's category">{t.customer_category ? CATEGORY_LABELS[t.customer_category] : "—"}</Row>
            <Row label="First queue">{t.first_queue ?? "—"}</Row>
            <Row label="Final queue">{t.final_queue ?? "—"}</Row>
            <Row label="Queue changes">{t.reassignment_count}</Row>
            <Row label="Reopened">{t.reopen_count}</Row>
            <Row label="Status">{t.status ?? "—"}</Row>
          </dl>
        </Card>
        <Card title="SLA">
          {!sla || !sla.applicable ? (
            <p className="text-sm text-text-muted">Not applicable: {humanize(sla?.not_applicable_reason ?? "not computed")}.</p>
          ) : (
            <dl>
              <Row label="Contract">
                {sla.tier} {sla.priority} · {sla.template_version}
              </Row>
              <Row label="Created">{formatIst(t.created_at)}</Row>
              <Row label={`First response (${sla.first_response_target_h} h)`}>
                <YesNo value={sla.first_response_breached} />
              </Row>
              <Row label="First response at">{formatIst(t.first_response_at)}</Row>
              <Row label={`Resolution (${sla.resolution_target_h} h)`}>
                <YesNo value={sla.resolution_breached} />
              </Row>
              <Row label="Resolved at">{formatIst(t.resolved_at)}</Row>
              <Row label="Resolution time">{sla.resolution_hours ? `${sla.resolution_hours} h` : "—"}</Row>
              {sla.credit_usd && (
                <Row label="Credit exposure">
                  {sla.credit_pct}% = USD {sla.credit_usd}
                  {sla.severity_multiplier === "1.5" ? " (×1.5)" : ""}
                </Row>
              )}
            </dl>
          )}
        </Card>
        <Card title="PII detections">
          {t.pii_detections.length === 0 ? (
            <p className="text-sm text-text-muted">None detected.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {t.pii_detections.map((d, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span className="font-mono text-xs">{d.token}</span>
                  <span className="text-xs text-text-muted">
                    {humanize(d.field)} · {d.method}
                    {d.checksum_valid === false ? " · checksum failed" : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <TicketRoutingCard ticketRef={t.external_id ?? t.id} />

      <Card title="Timeline">
        <ol className="space-y-2">
          {t.events.map((e) => (
            <li key={e.seq} className="flex flex-col gap-1 border-l-2 border-border pl-3 text-sm sm:flex-row sm:gap-4">
              <span className="w-44 shrink-0 text-xs text-text-muted">{formatIst(e.occurred_at)}</span>
              <span className="font-medium">{e.event_type}</span>
              <span className="text-text-muted">{e.actor}</span>
              <span className="font-mono text-xs break-all text-text-muted">
                {Object.entries(e.data)
                  .filter(([, v]) => v !== null && v !== "" && v !== false)
                  .map(([k, v]) => `${k}=${String(v)}`)
                  .join(" · ")}
              </span>
            </li>
          ))}
          {t.events.length === 0 && <p className="text-sm text-text-muted">This channel&apos;s export has no event history.</p>}
        </ol>
      </Card>

      <Card title="Normalization and provenance">
        <p className="mb-2 text-xs text-text-muted">
          Source: <span className="font-mono">{t.source_file}</span> record #{t.source_record_index}
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-text-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Field</th>
                <th className="py-1 pr-3 font-medium">Original</th>
                <th className="py-1 pr-3 font-medium">Normalized</th>
                <th className="py-1 font-medium">Rule</th>
              </tr>
            </thead>
            <tbody>
              {t.normalization.map((n, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="py-1 pr-3 font-mono">{n.field}</td>
                  <td className="py-1 pr-3">{n.original_value ?? "—"}</td>
                  <td className="py-1 pr-3 font-mono">{n.normalized_value ?? "—"}</td>
                  <td className="py-1 font-mono">{n.rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
