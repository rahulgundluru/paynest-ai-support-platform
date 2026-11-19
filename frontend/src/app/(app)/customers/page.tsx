"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Alert, Badge, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { apiFetch } from "@/lib/api";
import type { Customer, Page } from "@/types/api";


export default function CustomersPage() {
  const { data: user } = useCurrentUser();
  const allowed = hasPermission(user, "customers:read");
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("");
  const list = useQuery<Page<Customer>>({
    queryKey: ["customers", q, tier],
    queryFn: () => apiFetch(`/api/v1/customers?page_size=200${q ? `&q=${encodeURIComponent(q)}` : ""}${tier ? `&tier=${tier}` : ""}`),
    enabled: allowed,
    placeholderData: keepPreviousData,
  });
  if (!allowed) return <Alert tone="danger">You do not have permission to view customers.</Alert>;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Customers</h1>
        <p className="text-sm text-text-muted">Customer master from the contracts extract, with ticket and SLA exposure computed from ingested tickets.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Input className="max-w-xs" placeholder="Search name or id" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search customers" />
        <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Tier" className="rounded-md border border-border bg-surface px-2 py-2 text-sm">
          <option value="">All tiers</option>
          <option>Enterprise</option>
          <option>Business</option>
          <option>Standard</option>
        </select>
      </div>
      <Card title={`${list.data?.total ?? 0} customers`}>
        {list.isLoading ? (
          <Spinner />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-2 pr-3 font-medium">Customer</th>
                  <th className="py-2 pr-3 font-medium">Tier</th>
                  <th className="py-2 pr-3 font-medium">Region</th>
                  <th className="py-2 pr-3 font-medium">Fee / month</th>
                  <th className="py-2 pr-3 font-medium">Tickets</th>
                  <th className="py-2 pr-3 font-medium">SLA breaches</th>
                  <th className="py-2 font-medium">Credits</th>
                </tr>
              </thead>
              <tbody>
                {list.data?.items.map((c) => (
                  <tr key={c.customer_id} className="border-t border-border tabular-nums">
                    <td className="py-2 pr-3">
                      <Link href={`/customers/${c.customer_id}`} className="text-accent hover:underline">
                        {c.name}
                      </Link>
                      <div className="font-mono text-xs text-text-muted">{c.customer_id}</div>
                    </td>
                    <td className="py-2 pr-3">{c.tier}</td>
                    <td className="py-2 pr-3">{c.region}</td>
                    <td className="py-2 pr-3">USD {Number(c.monthly_fee_usd).toLocaleString()}</td>
                    <td className="py-2 pr-3">{c.ticket_count}</td>
                    <td className="py-2 pr-3">{c.sla_breaches > 0 ? <Badge tone="danger">{c.sla_breaches}</Badge> : 0}</td>
                    <td className="py-2">USD {Number(c.credits_usd).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
