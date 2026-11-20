"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import type { AuditLogEntry, Page } from "@/types/api";

const PAGE_SIZE = 25;

export default function AuditPage() {
  const { data: user } = useCurrentUser();
  const [page, setPage] = useState(1);
  const [actionInput, setActionInput] = useState("");
  const [action, setAction] = useState("");
  const allowed = hasPermission(user, "audit:read");

  const query = useQuery<Page<AuditLogEntry>>({
    queryKey: ["audit-logs", page, action],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (action) params.set("action", action);
      return apiFetch(`/api/v1/audit-logs?${params}`);
    },
    enabled: allowed,
    placeholderData: keepPreviousData,
  });

  if (!allowed) return <Alert tone="danger">You do not have permission to view the audit log.</Alert>;

  const totalPages = query.data ? Math.max(1, Math.ceil(query.data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Audit log</h1>
      <form
        className="flex max-w-md gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setAction(actionInput.trim());
        }}
      >
        <label htmlFor="action" className="sr-only">
          Filter by action
        </label>
        <Input id="action" placeholder="Filter by action, e.g. auth.login" value={actionInput} onChange={(e) => setActionInput(e.target.value)} />
        <Button type="submit" variant="secondary">
          Filter
        </Button>
      </form>
      <Card>
        {query.isLoading ? (
          <Spinner />
        ) : query.isError ? (
          <Alert tone="danger">
            Could not load the audit log
            {query.error instanceof ApiError ? ` (${query.error.message})` : ""}.
          </Alert>
        ) : query.data && query.data.items.length === 0 ? (
          <p className="text-sm text-text-muted">No audit events match this filter.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-text-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Time (UTC)</th>
                  <th className="py-2 pr-4 font-medium">Action</th>
                  <th className="py-2 pr-4 font-medium">Entity</th>
                  <th className="py-2 pr-4 font-medium">Actor</th>
                  <th className="py-2 font-medium">Request</th>
                </tr>
              </thead>
              <tbody>
                {query.data?.items.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <td className="py-2 pr-4 whitespace-nowrap">{new Date(row.occurred_at).toISOString().replace("T", " ").slice(0, 19)}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{row.action}</td>
                    <td className="py-2 pr-4">{row.entity_type ? `${row.entity_type}:${row.entity_id?.slice(0, 8)}` : "—"}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{row.actor_user_id?.slice(0, 8) ?? "—"}</td>
                    <td className="py-2 font-mono text-xs">{row.request_id?.slice(0, 8) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex items-center gap-3 text-sm">
        <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </Button>
        <span className="text-text-muted">
          Page {page} of {totalPages} · {query.data?.total ?? 0} events
        </span>
        <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
