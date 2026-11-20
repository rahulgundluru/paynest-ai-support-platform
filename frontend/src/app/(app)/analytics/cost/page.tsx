"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { StatTile } from "@/components/charts";
import { Alert, Badge, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { apiFetch } from "@/lib/api";
import { humanize } from "@/lib/format";

interface Input_ {
  value: string | number | null;
  provenance: string;
}
interface Scenario {
  inputs: Record<string, Input_>;
  ai_platform_cost_usd_month: string;
  within_budget_cap: boolean;
  budget_headroom_usd: string;
  credits_avoided_usd_month: string;
  net_cash_effect_usd_month: string;
  cost_per_ticket_incl_credits_usd: string;
  released_capacity_hours_month: string;
  released_capacity_fte: string;
  payback_months: string | null;
  payback_note: string | null;
}
interface Baseline {
  period: string;
  support_cost_usd_month: string;
  tickets_month: string;
  sla_credits_usd_month: string;
  cost_per_ticket_excl_credits_usd: string;
  cost_per_ticket_incl_credits_usd: string;
  addressable_credit_share: string;
  budget_cap_usd_month: string;
}
interface CostView {
  baseline: Baseline;
  measured_ai: { draft_calls: number; note: string | null };
  assumptions: Record<string, Input_>;
  scenarios: Record<string, Scenario>;
  notes: string[];
}

const PROVENANCE_TONE: Record<string, "success" | "neutral" | "danger"> = { measured: "success", source_estimate: "neutral", assumption: "danger" };
const money = (v: string) => `USD ${Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function CostPage() {
  const { data: user } = useCurrentUser();
  const allowed = hasPermission(user, "sla:read");
  const [impl, setImpl] = useState("");
  const [minutes, setMinutes] = useState("4");
  const params = new URLSearchParams({ minutes_saved_per_draft: minutes || "0" });
  if (impl) params.set("implementation_cost_usd", impl);
  const cost = useQuery<CostView>({
    queryKey: ["cost", impl, minutes],
    queryFn: () => apiFetch(`/api/v1/analytics/cost?${params}`),
    enabled: allowed,
    placeholderData: keepPreviousData,
  });

  if (!allowed) return <Alert tone="danger">You do not have permission to view cost analytics.</Alert>;
  if (cost.isLoading || !cost.data) return <Spinner />;
  const c = cost.data;
  const b = c.baseline;
  const names = ["best", "expected", "conservative"];
  const rows: [string, (s: Scenario) => string][] = [
    ["AI platform cost / month", (s) => money(s.ai_platform_cost_usd_month)],
    ["Within USD 4,500 cap", (s) => (s.within_budget_cap ? `yes (headroom ${money(s.budget_headroom_usd)})` : "no")],
    ["SLA credits avoided / month", (s) => money(s.credits_avoided_usd_month)],
    ["Net cash effect / month", (s) => money(s.net_cash_effect_usd_month)],
    ["Cost per ticket incl. credits", (s) => money(s.cost_per_ticket_incl_credits_usd)],
    ["Released agent capacity", (s) => `${Number(s.released_capacity_hours_month).toLocaleString()} h (${s.released_capacity_fte} FTE)`],
    ["Payback", (s) => (s.payback_months ? `${s.payback_months} months` : (s.payback_note ?? "—"))],
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Cost analytics</h1>
        <p className="text-sm text-text-muted">
          Every input is labelled: <Badge tone="success">measured</Badge> <Badge>source estimate</Badge> <Badge tone="danger">assumption</Badge>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Support cost / month (measured)" value={money(b.support_cost_usd_month)} sub={`${b.period} · agents + tooling`} />
        <StatTile label="Tickets / month (measured)" value={Number(b.tickets_month).toLocaleString()} sub="all customers" />
        <StatTile label="Cost per ticket (measured)" value={money(b.cost_per_ticket_excl_credits_usd)} sub={`${money(b.cost_per_ticket_incl_credits_usd)} incl. credits`} />
        <StatTile label="SLA credits / month (measured)" value={money(b.sla_credits_usd_month)} sub={`${b.addressable_credit_share} from misrouting or stale answers`} />
      </div>

      <Card title="Assumptions you can change">
        <form className="flex flex-wrap items-end gap-4" onSubmit={(e) => e.preventDefault()}>
          <div className="space-y-1">
            <label htmlFor="impl" className="text-xs text-text-muted">
              One-time implementation cost (USD), not in the sources
            </label>
            <Input id="impl" type="number" min={0} value={impl} onChange={(e) => setImpl(e.target.value)} placeholder="e.g. 20000" className="w-48" />
          </div>
          <div className="space-y-1">
            <label htmlFor="minutes" className="text-xs text-text-muted">
              Agent minutes saved per AI draft
            </label>
            <Input id="minutes" type="number" min={0} max={60} value={minutes} onChange={(e) => setMinutes(e.target.value)} className="w-28" />
          </div>
        </form>
        {c.measured_ai.note && <p className="mt-3 text-xs text-text-muted">{c.measured_ai.note}</p>}
      </Card>

      <Card title="Scenarios">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-text-muted">
              <tr>
                <th className="py-2 pr-4 font-medium" />
                {names.map((n) => (
                  <th key={n} className="py-2 pr-4 font-medium">
                    {humanize(n)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.keys(c.scenarios.expected?.inputs ?? {}).map((k) => (
                <tr key={k} className="border-t border-border">
                  <td className="py-2 pr-4 text-text-muted">{humanize(k)}</td>
                  {names.map((n) => {
                    const input = c.scenarios[n]!.inputs[k]!;
                    return (
                      <td key={n} className="py-2 pr-4 tabular-nums">
                        {String(input.value)} <Badge tone={PROVENANCE_TONE[input.provenance] ?? "neutral"}>{humanize(input.provenance)}</Badge>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {rows.map(([label, fn]) => (
                <tr key={label} className="border-t border-border font-medium">
                  <td className="py-2 pr-4">{label}</td>
                  {names.map((n) => (
                    <td key={n} className="py-2 pr-4 tabular-nums">
                      {fn(c.scenarios[n]!)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-text-muted">
          {c.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
