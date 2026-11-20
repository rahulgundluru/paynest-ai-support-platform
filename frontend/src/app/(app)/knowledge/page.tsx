"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { KnowledgeDocumentDetail, KnowledgeDocument, Page, RateInForce, SearchResponse } from "@/types/api";

function Window({ from, to }: { from: string | null; to: string | null }) {
  return (
    <span className="font-mono text-xs">
      {from ?? "…"} → {to ?? "in force"}
    </span>
  );
}

function RetrievalTester() {
  const [query, setQuery] = useState("What is the current PF wage ceiling?");
  const [region, setRegion] = useState("IN");
  const [asOf, setAsOf] = useState("2026-09-15");
  const search = useMutation({
    mutationFn: () =>
      apiFetch<SearchResponse>("/api/v1/knowledge/search", {
        method: "POST",
        body: JSON.stringify({ query, region, as_of: asOf, limit: 6 }),
      }),
  });
  const rates = useQuery<RateInForce[]>({
    queryKey: ["rates", region, asOf],
    queryFn: () => apiFetch(`/api/v1/statutory/rates?region=${region}&as_of=${asOf}`),
  });

  return (
    <Card title="Retrieval tester (date- and region-aware)">
      <form
        className="grid gap-3 sm:grid-cols-3 xl:grid-cols-[minmax(0,1fr)_auto_auto_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          search.mutate();
        }}
      >
        <div className="space-y-1 sm:col-span-3 xl:col-span-1">
          <label htmlFor="kq" className="text-xs text-text-muted">
            Question (redacted before search)
          </label>
          <Input id="kq" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label htmlFor="kr" className="text-xs text-text-muted">
            Region
          </label>
          <select id="kr" value={region} onChange={(e) => setRegion(e.target.value)} className="w-full rounded-md border border-border bg-surface px-2 py-2 text-sm">
            <option value="IN">India</option>
            <option value="UAE">UAE</option>
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="kd" className="text-xs text-text-muted">
            As of (ticket date)
          </label>
          <Input id="kd" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={search.isPending || query.trim().length < 2}>
            {search.isPending ? "Searching…" : "Search"}
          </Button>
        </div>
      </form>

      {rates.data && rates.data.length > 0 && (
        <div className="mt-4 rounded-md bg-surface-muted p-3 text-sm">
          <p className="mb-1 text-xs text-text-muted">Statutory parameters in force on {asOf} ({region})</p>
          <ul className="space-y-1">
            {rates.data.map((r) => (
              <li key={r.rule_id}>
                <span className="font-mono text-xs">{r.rule_id}</span> · {r.title}: <strong>{r.value}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}

      {search.isError && (
        <div className="mt-3">
          <Alert tone="danger">Search failed{search.error instanceof ApiError ? `: ${search.error.message}` : ""}.</Alert>
        </div>
      )}
      {search.data && (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-text-muted">
            Searched for: <span className="font-mono">{search.data.query_redacted}</span> · mode {search.data.mode}
          </p>
          {search.data.hits.length === 0 ? (
            <Alert tone="warning">No knowledge in force on this date matches: insufficient evidence, route to a person.</Alert>
          ) : (
            <ol className="space-y-2">
              {search.data.hits.map((h) => (
                <li key={`${h.document_id}-${h.rank}`} className="rounded-md border border-border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs">#{h.rank}</span>
                    <span className="font-medium">
                      {h.document_id} v{h.version}
                    </span>
                    <Badge>{humanize(h.doc_type)}</Badge>
                    {!h.content_complete && <Badge tone="danger">title only</Badge>}
                    <Window from={h.effective_from} to={h.effective_to} />
                  </div>
                  <p className="mt-1 text-text-muted">{h.text.slice(0, 280)}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Card>
  );
}

export default function KnowledgePage() {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const docs = useQuery<Page<KnowledgeDocument>>({
    queryKey: ["knowledge-docs"],
    queryFn: () => apiFetch("/api/v1/knowledge/documents?page_size=100"),
    enabled: hasPermission(user, "knowledge:read"),
  });
  const detail = useQuery<KnowledgeDocumentDetail>({
    queryKey: ["knowledge-doc", selected],
    queryFn: () => apiFetch(`/api/v1/knowledge/documents/${encodeURIComponent(selected!)}`),
    enabled: !!selected,
  });
  const reindex = useMutation({
    mutationFn: () => apiFetch<Record<string, number>>("/api/v1/knowledge/index", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-docs"] }),
  });

  if (!hasPermission(user, "knowledge:read")) return <Alert tone="danger">You do not have permission to view the knowledge base.</Alert>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Knowledge base</h1>
          <p className="text-sm text-text-muted">
            Every version carries an effective-date window. Retrieval only returns content in force on the question&apos;s date.
          </p>
        </div>
        {hasPermission(user, "knowledge:manage") && (
          <Button variant="secondary" onClick={() => reindex.mutate()} disabled={reindex.isPending}>
            {reindex.isPending ? "Indexing…" : "Re-index from source"}
          </Button>
        )}
      </div>
      {reindex.isSuccess && (
        <Alert tone="success">
          Indexed: {Object.entries(reindex.data).map(([k, v]) => `${humanize(k)} ${v}`).join(" · ")}
        </Alert>
      )}

      <RetrievalTester />

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Documents" className="lg:col-span-3">
          {docs.isLoading ? (
            <Spinner />
          ) : docs.data?.total === 0 ? (
            <p className="text-sm text-text-muted">Nothing indexed yet. A KB owner or admin can re-index from source.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-text-muted">
                  <tr>
                    <th className="py-2 pr-3 font-medium">Id</th>
                    <th className="py-2 pr-3 font-medium">Title</th>
                    <th className="py-2 pr-3 font-medium">Region</th>
                    <th className="py-2 font-medium">Today</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.data?.items.map((d) => (
                    <tr key={d.id} className={`border-t border-border ${selected === d.id ? "bg-surface-muted" : ""}`}>
                      <td className="py-2 pr-3 font-mono text-xs">
                        <button type="button" className="text-accent hover:underline" onClick={() => setSelected(d.id)}>
                          {d.id}
                        </button>
                      </td>
                      <td className="py-2 pr-3">{d.title}</td>
                      <td className="py-2 pr-3">{d.region}</td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-1">
                          <Badge tone={d.in_force_today ? "success" : "danger"}>{d.in_force_today ? "in force" : "superseded"}</Badge>
                          {!d.content_complete && <Badge>title only</Badge>}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title={selected ? `Versions · ${selected}` : "Versions"} className="lg:col-span-2">
          {!selected ? (
            <p className="text-sm text-text-muted">Select a document to see its versions and validity windows.</p>
          ) : detail.isLoading ? (
            <Spinner />
          ) : (
            <div className="space-y-3 text-sm">
              <p className="text-xs text-text-muted">
                Source <span className="font-mono">{detail.data?.source_file}</span>
                {detail.data?.last_reviewed ? ` · last reviewed ${detail.data.last_reviewed} (not an effective date)` : ""}
              </p>
              {detail.data?.versions.map((v) => (
                <div key={v.id} className="rounded-md border border-border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">v{v.version}</span>
                    <Window from={v.effective_from} to={v.effective_to} />
                    <Badge>{v.validity_source}</Badge>
                    {v.superseded_by && <Badge tone="danger">superseded by {v.superseded_by}</Badge>}
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-text-muted">{v.content.slice(0, 600)}</p>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
