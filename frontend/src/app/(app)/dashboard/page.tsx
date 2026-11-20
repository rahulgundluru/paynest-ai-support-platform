"use client";

import { useQuery } from "@tanstack/react-query";

import { ChartCard, ColumnChart, DailyLineChart, HBarChart, StatTile } from "@/components/charts";
import { Alert, Badge, Card, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { apiFetch } from "@/lib/api";
import { CATEGORY_LABELS, CHANNEL_LABELS } from "@/lib/format";
import type { ReadyResponse } from "@/types/api";

interface Summary {
  tickets: { total: number; closed_or_resolved: number; open: number; ingestion_requires_review: number; payroll_window_share: number | null };
  first_response_hours: { mean: number | null; median: number | null };
  sla: { applicable: number; resolution_breaches: number; credits_usd: string; first_response_breaches: number };
  duplicates: { resubmission_cases: number; resubmitted_tickets: number; incidents: number };
  ai: { classified_tickets: number; note: string | null; routing_decisions: number; lanes: Record<string, number>; automation_rate: number | null; automation_note: string };
  human_review: { pending: number; by_status: Record<string, number> };
  routing_baseline: { first_touch_correct: number; routed: number; rate: number | null; note: string };
}
interface Breakdowns {
  channel: { key: string; count: number }[];
  region: { key: string; count: number }[];
  customer_category: { key: string; count: number }[];
  final_queue: { key: string; count: number }[];
  priority: { key: string; count: number }[];
}
interface Trends {
  days: { day: string; tickets: number; payroll_window: boolean; grouped_into_cases: number }[];
}
interface SlaPerformance {
  attribution_note: string;
  by_contract: { tier: string; priority: string; tickets: number; breaches: number; credits_usd: string }[];
  by_month: { month: string; breaches: number; credits_usd: string; breach_rate: number | null }[];
  credits_from_tickets_that_changed_queue: { credits_usd: string; share: number | null };
}
interface RoutingPerformance {
  queues: { queue: string; tickets: number; stayed: number; rate: number | null; payroll_window_rate: number | null }[];
}

const pct = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`);
const categoryLabel = (key: string) => (key === "unknown" ? "None (WhatsApp/phone)" : (CATEGORY_LABELS[key] ?? key));
const usd = (v: number) => `USD ${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

export default function DashboardPage() {
  const { data: user } = useCurrentUser();
  const allowed = hasPermission(user, "tickets:read");
  const get = <T,>(path: string) => ({ queryKey: [path], queryFn: () => apiFetch<T>(path), enabled: allowed });
  const summary = useQuery(get<Summary>("/api/v1/dashboard/summary"));
  const breakdowns = useQuery(get<Breakdowns>("/api/v1/dashboard/breakdowns"));
  const trends = useQuery(get<Trends>("/api/v1/dashboard/ticket-trends"));
  const sla = useQuery(get<SlaPerformance>("/api/v1/dashboard/sla-performance"));
  const routing = useQuery(get<RoutingPerformance>("/api/v1/dashboard/routing-performance"));
  const status = useQuery<ReadyResponse>({
    queryKey: ["system", "ready"],
    queryFn: async () => (await fetch("/system/ready", { cache: "no-store" })).json(),
    refetchInterval: 30_000,
  });

  if (!allowed) {
    return <Alert tone="warning">Your role has no access to ticket analytics. Use the pages in the navigation available to you.</Alert>;
  }
  const s = summary.data;
  if (summary.isLoading) return <Spinner label="Loading dashboard" />;
  if (summary.isError || !s) return <Alert tone="danger">Could not load the dashboard.</Alert>;
  if (s.tickets.total === 0) {
    return <Alert tone="warning">No tickets have been ingested yet. Run ingestion from the Data ingestion page; nothing here is estimated.</Alert>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Support operations dashboard</h1>
          <p className="text-sm text-text-muted">
            Computed live from ingested data for your regions ({user?.regions.join(", ")}). Dates in IST.
          </p>
        </div>
        <Badge tone={status.data?.status === "ok" ? "success" : "danger"}>system {status.data?.status ?? "…"}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatTile label="Tickets" value={s.tickets.total.toLocaleString()} sub={`${s.tickets.open} open · ${pct(s.tickets.payroll_window_share, 0)} in payroll window`} />
        <StatTile label="SLA breaches" value={s.sla.resolution_breaches} sub={`${usd(Number(s.sla.credits_usd))} credits`} />
        <StatTile label="Waiting for a person" value={s.human_review.pending} sub="review queue" />
        <StatTile label="Grouped cases" value={s.duplicates.resubmission_cases + s.duplicates.incidents} sub={`${s.duplicates.resubmission_cases} resubmissions · ${s.duplicates.incidents} incidents`} />
        <StatTile label="Median first response" value={s.first_response_hours.median === null ? "—" : `${s.first_response_hours.median.toFixed(1)} h`} sub={`mean ${s.first_response_hours.mean?.toFixed(1) ?? "—"} h`} />
        <StatTile label="Routed right first time" value={pct(s.routing_baseline.rate)} sub={`baseline: customer's own pick (${s.routing_baseline.first_touch_correct}/${s.routing_baseline.routed})`} />
        <StatTile label="AI-classified tickets" value={s.ai.classified_tickets} sub={s.ai.note ?? "with a model configured"} />
        <StatTile label="Automation rate" value={pct(s.ai.automation_rate)} sub={s.ai.automation_note} />
        <StatTile label="Routing lanes" value={s.ai.routing_decisions.toLocaleString()} sub={Object.entries(s.ai.lanes).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")} />
        <StatTile label="Needs data review" value={s.tickets.ingestion_requires_review} sub="from ingestion (identity, priority)" />
      </div>

      {trends.data && (
        <ChartCard
          title="Tickets per day"
          description="Shaded days are the payroll window (25th–3rd)."
          table={{ columns: ["Day", "Tickets", "Payroll window", "Grouped into cases"], rows: trends.data.days.map((d) => [d.day, d.tickets, d.payroll_window ? "yes" : "no", d.grouped_into_cases]) }}
        >
          <DailyLineChart data={trends.data.days.map((d) => ({ day: d.day, value: d.tickets, band: d.payroll_window }))} valueLabel="Tickets" />
        </ChartCard>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {sla.data && (
          <ChartCard
            title="SLA credits by month (USD)"
            description={`${sla.data.attribution_note} ${pct(sla.data.credits_from_tickets_that_changed_queue.share)} of credits came from tickets that changed queue.`}
            table={{ columns: ["Month", "Breaches", "Credits (USD)", "Breach rate"], rows: sla.data.by_month.map((m) => [m.month, m.breaches, m.credits_usd, pct(m.breach_rate)]) }}
          >
            <ColumnChart
              data={sla.data.by_month.map((m) => ({ label: m.month, value: Number(m.credits_usd), extra: String(m.breaches) }))}
              valueLabel="Credits"
              format={(v) => usd(v)}
              axisFormat={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))}
              extra="Breaches"
            />
          </ChartCard>
        )}
        {routing.data && (
          <ChartCard
            title="Tickets that stayed in their first queue"
            description="Today's routing (customer's category pick), by the queue they were first sent to."
            table={{ columns: ["First queue", "Tickets", "Stayed", "Rate", "Payroll window rate"], rows: routing.data.queues.map((q) => [q.queue, q.tickets, q.stayed, pct(q.rate), pct(q.payroll_window_rate)]) }}
          >
            <HBarChart data={routing.data.queues.map((q) => ({ label: q.queue, value: q.rate ?? 0 }))} valueLabel="Stayed" format={(v) => pct(v, 0)} />
          </ChartCard>
        )}
      </div>

      {breakdowns.data && (
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard title="Tickets by channel" table={{ columns: ["Channel", "Tickets"], rows: breakdowns.data.channel.map((r) => [CHANNEL_LABELS[r.key] ?? r.key, r.count]) }}>
            <HBarChart data={breakdowns.data.channel.map((r) => ({ label: CHANNEL_LABELS[r.key] ?? r.key, value: r.count }))} valueLabel="Tickets" />
          </ChartCard>
          <ChartCard title="Customer's category pick" table={{ columns: ["Category", "Tickets"], rows: breakdowns.data.customer_category.map((r) => [categoryLabel(r.key), r.count]) }}>
            <HBarChart data={breakdowns.data.customer_category.map((r) => ({ label: categoryLabel(r.key), value: r.count }))} valueLabel="Tickets" />
          </ChartCard>
          <ChartCard title="Tickets by region" table={{ columns: ["Region", "Tickets"], rows: breakdowns.data.region.map((r) => [r.key, r.count]) }}>
            <HBarChart data={breakdowns.data.region.map((r) => ({ label: r.key === "unknown" ? "Unknown (unverified)" : r.key, value: r.count }))} valueLabel="Tickets" />
          </ChartCard>
        </div>
      )}

      {sla.data && (
        <Card title="SLA by contract tier and priority">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Tier</th>
                  <th className="py-2 pr-4 font-medium">Priority</th>
                  <th className="py-2 pr-4 font-medium">Tickets</th>
                  <th className="py-2 pr-4 font-medium">Breaches</th>
                  <th className="py-2 font-medium">Credits (USD)</th>
                </tr>
              </thead>
              <tbody>
                {sla.data.by_contract.map((r) => (
                  <tr key={`${r.tier}-${r.priority}`} className="border-t border-border tabular-nums">
                    <td className="py-2 pr-4">{r.tier}</td>
                    <td className="py-2 pr-4">{r.priority}</td>
                    <td className="py-2 pr-4">{r.tickets}</td>
                    <td className="py-2 pr-4">{r.breaches}</td>
                    <td className="py-2">{Number(r.credits_usd).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
