"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, Input, Spinner } from "@/components/ui";
import { hasPermission, useCurrentUser } from "@/hooks/use-auth";
import { ApiError, apiFetch } from "@/lib/api";
import { formatIst, humanize } from "@/lib/format";

interface RuntimeSetting {
  key: string;
  label: string;
  kind: "float" | "int" | "bool";
  value: number | boolean;
  default: number | boolean;
  minimum: number | null;
  maximum: number | null;
  editable: boolean;
  locked_reason: string | null;
  updated_at: string | null;
}
interface SettingsView {
  runtime: RuntimeSetting[];
  models: Record<string, string>;
  privacy: Record<string, string | number>;
  routing_rules: { rule_id: string; lane: string; description: string }[];
  sla_terms: { tier: string; priority: string; first_response_h: string; resolution_h: string; credit_pct: string }[];
  regions: { code: string; name: string; data_residency: string }[];
  roles: Record<string, string[]>;
  versions: Record<string, string>;
}

function RuntimeRow({ s, canEdit }: { s: RuntimeSetting; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(s.value));
  const save = useMutation({
    mutationFn: () =>
      apiFetch<{ settings: SettingsView }>("/api/v1/settings", {
        method: "PATCH",
        body: JSON.stringify({ [s.key]: s.kind === "int" ? parseInt(value, 10) : parseFloat(value) }),
      }),
    onSuccess: (data) => queryClient.setQueryData(["settings"], data.settings),
  });
  const editable = canEdit && s.editable && s.kind !== "bool";
  return (
    <tr className="border-t border-border align-top">
      <td className="py-2 pr-3">
        <p>{s.label}</p>
        <p className="font-mono text-xs text-text-muted">{s.key}</p>
        {s.locked_reason && <p className="text-xs text-text-muted">{s.locked_reason}</p>}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {editable ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <Input
              type="number"
              value={value}
              min={s.minimum ?? undefined}
              max={s.maximum ?? undefined}
              step={s.kind === "int" ? 1 : 0.01}
              onChange={(e) => setValue(e.target.value)}
              className="w-24"
              aria-label={s.label}
            />
            <Button type="submit" variant="secondary" disabled={save.isPending || value === String(s.value)}>
              Save
            </Button>
          </form>
        ) : (
          <span className="font-mono">{String(s.value)}</span>
        )}
        {save.isError && <p className="mt-1 text-xs text-danger">{save.error instanceof ApiError ? save.error.message : "Failed"}</p>}
      </td>
      <td className="py-2 pr-3 text-xs text-text-muted whitespace-nowrap">
        {s.minimum !== null ? `${s.minimum} – ${s.maximum}` : "—"} · default {String(s.default)}
      </td>
      <td className="py-2 text-xs text-text-muted whitespace-nowrap">{s.updated_at ? formatIst(s.updated_at) : "default"}</td>
    </tr>
  );
}

export default function SettingsPage() {
  const { data: user } = useCurrentUser();
  const canRead = hasPermission(user, "settings:read");
  const canEdit = hasPermission(user, "settings:manage");
  const settings = useQuery<SettingsView>({ queryKey: ["settings"], queryFn: () => apiFetch("/api/v1/settings"), enabled: canRead });

  if (!canRead) return <Alert tone="danger">You do not have permission to view settings.</Alert>;
  if (settings.isLoading || !settings.data) return <Spinner />;
  const v = settings.data;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-text-muted">
          Runtime settings are bounded and audited{canEdit ? "" : " (read-only for your role)"}. Credentials are never shown here.
        </p>
      </div>

      <Card title="Runtime settings">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-text-muted">
              <tr>
                <th className="py-2 pr-3 font-medium">Setting</th>
                <th className="py-2 pr-3 font-medium">Value</th>
                <th className="py-2 pr-3 font-medium">Allowed</th>
                <th className="py-2 font-medium">Last changed</th>
              </tr>
            </thead>
            <tbody>
              {v.runtime.map((s) => (
                <RuntimeRow key={`${s.key}-${String(s.value)}`} s={s} canEdit={canEdit} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="AI models">
          <dl className="space-y-1 text-sm">
            {Object.entries(v.models).map(([k, val]) => (
              <div key={k} className="flex flex-wrap justify-between gap-2">
                <dt className="text-text-muted">{humanize(k)}</dt>
                <dd className="text-right">{val}</dd>
              </div>
            ))}
          </dl>
        </Card>
        <Card title="Privacy and regions">
          <dl className="space-y-1 text-sm">
            {Object.entries(v.privacy).map(([k, val]) => (
              <div key={k} className="flex flex-wrap justify-between gap-2">
                <dt className="text-text-muted">{humanize(k)}</dt>
                <dd className="text-right">{String(val)}</dd>
              </div>
            ))}
            {v.regions.map((r) => (
              <div key={r.code} className="flex flex-wrap justify-between gap-2">
                <dt className="text-text-muted">{r.name}</dt>
                <dd>{r.data_residency}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <Card title="Routing rules (deterministic, evaluated in order)">
        <ol className="space-y-1 text-sm">
          {v.routing_rules.map((r) => (
            <li key={r.rule_id} className="flex flex-wrap gap-2">
              <span className="font-mono text-xs">{r.rule_id}</span>
              <Badge>{humanize(r.lane)}</Badge>
              <span>{r.description}</span>
            </li>
          ))}
        </ol>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="SLA terms (contract template v3.2)">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-text-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Tier</th>
                <th className="py-1 pr-3 font-medium">Priority</th>
                <th className="py-1 pr-3 font-medium">First response</th>
                <th className="py-1 pr-3 font-medium">Resolution</th>
                <th className="py-1 font-medium">Credit</th>
              </tr>
            </thead>
            <tbody>
              {v.sla_terms.map((t) => (
                <tr key={`${t.tier}-${t.priority}`} className="border-t border-border tabular-nums">
                  <td className="py-1 pr-3">{t.tier}</td>
                  <td className="py-1 pr-3">{t.priority}</td>
                  <td className="py-1 pr-3">{Number(t.first_response_h)} h</td>
                  <td className="py-1 pr-3">{Number(t.resolution_h)} h</td>
                  <td className="py-1">{Number(t.credit_pct)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-text-muted">Standard tier: best effort, no credits.</p>
        </Card>
        <Card title="Rule and prompt versions">
          <dl className="space-y-1 text-sm">
            {Object.entries(v.versions).map(([k, val]) => (
              <div key={k} className="flex justify-between gap-2">
                <dt className="text-text-muted">{humanize(k)}</dt>
                <dd className="font-mono text-xs">{val}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <Card title="Roles and permissions">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <tbody>
              {Object.entries(v.roles).map(([role, perms]) => (
                <tr key={role} className="border-t border-border align-top">
                  <td className="py-2 pr-3 font-medium whitespace-nowrap">{humanize(role)}</td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-1">
                      {perms.length ? perms.map((p) => <Badge key={p}>{p}</Badge>) : <span className="text-text-muted">none</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
