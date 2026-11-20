"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Alert, Badge, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { humanize } from "@/lib/format";

interface Overview {
  tickets: number;
  stages: { stage: string; counts: Record<string, number>; note?: string }[];
}
interface TicketStatus {
  ticket: string;
  stages: { stage: string; status: string; detail: string }[];
}

const TONE: Record<string, "success" | "danger" | "neutral"> = {
  done: "success",
  not_required: "success",
  review: "danger",
  failed: "danger",
  missing: "danger",
  pending: "neutral",
  unavailable: "neutral",
  not_run: "neutral",
};

export default function ProcessingPage() {
  const { data: user } = useCurrentUser();
  const allowed = hasPermission(user, "tickets:read");
  const [input, setInput] = useState("PN-101129");
  const [ref, setRef] = useState("PN-101129");
  const overview = useQuery<Overview>({
    queryKey: ["processing-overview"],
    queryFn: () => apiFetch("/api/v1/processing/overview"),
    enabled: allowed,
  });
  const status = useQuery<TicketStatus>({
    queryKey: ["processing-status", ref],
    queryFn: () => apiFetch(`/api/v1/processing/${encodeURIComponent(ref)}/status`),
    enabled: allowed && !!ref,
    retry: false,
  });

  if (!allowed) return <Alert tone="danger">You do not have permission to view the processing monitor.</Alert>;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Processing monitor</h1>
        <p className="text-sm text-text-muted">
          Each stage&apos;s status is read from what the pipeline stored, not inferred. Stages that need an AI model show as unavailable.
        </p>
      </div>

      <Card title="One ticket through the pipeline">
        <form
          className="mb-4 flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setRef(input.trim());
          }}
        >
          <Input value={input} onChange={(e) => setInput(e.target.value)} aria-label="Ticket id" placeholder="PN-100921" />
          <Button type="submit" variant="secondary">
            Show
          </Button>
        </form>
        {status.isLoading ? (
          <Spinner />
        ) : status.isError ? (
          <Alert tone="danger">{status.error instanceof ApiError && status.error.status === 404 ? "Ticket not found in your regions." : "Could not load status."}</Alert>
        ) : status.data ? (
          <ol className="space-y-1">
            {status.data.stages.map((s, i) => (
              <li key={s.stage} className="grid grid-cols-[1.5rem_10rem_6.5rem_1fr] items-center gap-2 text-sm">
                <span className="text-xs text-text-muted tabular-nums">{i + 1}</span>
                <span className="font-medium">{humanize(s.stage)}</span>
                <span>
                  <Badge tone={TONE[s.status] ?? "neutral"}>{humanize(s.status)}</Badge>
                </span>
                <span className="text-text-muted">{s.detail}</span>
              </li>
            ))}
            <li className="pt-2 text-sm">
              <Link href={`/tickets/${status.data.ticket}`} className="text-accent hover:underline">
                Open {status.data.ticket}
              </Link>
            </li>
          </ol>
        ) : null}
      </Card>

      <Card title={`All tickets in your regions (${overview.data?.tickets ?? "…"})`}>
        {overview.isLoading ? (
          <Spinner />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Stage</th>
                  <th className="py-2 font-medium">Counts</th>
                </tr>
              </thead>
              <tbody>
                {overview.data?.stages.map((s) => (
                  <tr key={s.stage} className="border-t border-border align-top">
                    <td className="py-2 pr-4 font-medium whitespace-nowrap">{humanize(s.stage)}</td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(s.counts).map(([k, v]) => (
                          <Badge key={k}>
                            {humanize(k)}: {v}
                          </Badge>
                        ))}
                      </div>
                      {s.note && <p className="mt-1 text-xs text-text-muted">{s.note}</p>}
                    </td>
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
