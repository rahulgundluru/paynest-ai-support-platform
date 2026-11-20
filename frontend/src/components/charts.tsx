"use client";

/**
 * Chart primitives. Single-series charts only (one validated colour, --series-1); identity is never
 * carried by colour alone, every chart has a hover tooltip and a table view, grid/axes are recessive.
 */
import { useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui";

const AXIS = { fontSize: 11, fill: "var(--chart-axis)" };

export function StatTile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs text-text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-1 text-xs text-text-muted">{sub}</p>}
    </div>
  );
}

function TooltipBox({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="font-medium">{title}</p>
      {rows.map(([k, v]) => (
        <p key={k} className="text-text-muted">
          {k}: <span className="text-text tabular-nums">{v}</span>
        </p>
      ))}
    </div>
  );
}

export function ChartCard({
  title,
  description,
  table,
  children,
}: {
  title: string;
  description?: string;
  table: { columns: string[]; rows: (string | number)[][] };
  children: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="text-xs text-text-muted">{description}</p>}
        </div>
        <button type="button" onClick={() => setShowTable((v) => !v)} className="text-xs text-accent hover:underline" aria-pressed={showTable}>
          {showTable ? "Show chart" : "Show table"}
        </button>
      </div>
      {showTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-text-muted">
              <tr>
                {table.columns.map((c) => (
                  <th key={c} className="py-1 pr-3 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-t border-border">
                  {r.map((v, j) => (
                    <td key={j} className="py-1 pr-3 tabular-nums">
                      {v}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </Card>
  );
}

/** Daily volume line, with payroll-window days shaded as a neutral background band (not a series colour). */
export function DailyLineChart({
  data,
  valueLabel,
}: {
  data: { day: string; value: number; band: boolean }[];
  valueLabel: string;
}) {
  const bands: [string, string][] = [];
  let start: string | null = null;
  data.forEach((d, i) => {
    if (d.band && start === null) start = d.day;
    if (start !== null && (!d.band || i === data.length - 1)) {
      bands.push([start, d.band ? d.day : data[i - 1]!.day]);
      start = null;
    }
  });
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          {bands.map(([a, b]) => (
            <ReferenceArea key={a} x1={a} x2={b} fill="var(--surface-muted)" fillOpacity={1} ifOverflow="extendDomain" />
          ))}
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="day" tick={AXIS} tickLine={false} axisLine={false} minTickGap={28} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip
            cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }}
            content={({ active, payload }) =>
              active && payload?.[0] ? (
                <TooltipBox
                  title={String(payload[0].payload.day)}
                  rows={[
                    [valueLabel, String(payload[0].value)],
                    ["Payroll window", payload[0].payload.band ? "yes" : "no"],
                  ]}
                />
              ) : null
            }
          />
          <Line type="linear" dataKey="value" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal bars for a ranked breakdown. */
export function HBarChart({
  data,
  valueLabel,
  format = (v) => String(v),
}: {
  data: { label: string; value: number }[];
  valueLabel: string;
  format?: (v: number) => string;
}) {
  const height = Math.max(120, data.length * 30 + 24);
  const labelWidth = Math.min(150, Math.max(48, ...data.map((d) => d.label.length * 6.5 + 8)));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 8 }} barCategoryGap={2}>
          <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
          <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v: number) => format(v)} />
          <YAxis type="category" dataKey="label" tick={AXIS} tickLine={false} axisLine={false} width={labelWidth} />
          <Tooltip
            cursor={{ fill: "var(--surface-muted)" }}
            content={({ active, payload }) =>
              active && payload?.[0] ? (
                <TooltipBox title={String(payload[0].payload.label)} rows={[[valueLabel, format(Number(payload[0].value))]]} />
              ) : null
            }
          />
          <Bar dataKey="value" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Vertical columns for a short time series (e.g. per month). */
export function ColumnChart({
  data,
  valueLabel,
  format = (v) => String(v),
  axisFormat,
  extra,
}: {
  data: { label: string; value: number; extra?: string }[];
  valueLabel: string;
  format?: (v: number) => string;
  axisFormat?: (v: number) => string;
  extra?: string;
}) {
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barCategoryGap="30%">
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v: number) => (axisFormat ?? format)(v)} width={48} />
          <Tooltip
            cursor={{ fill: "var(--surface-muted)" }}
            content={({ active, payload }) =>
              active && payload?.[0] ? (
                <TooltipBox
                  title={String(payload[0].payload.label)}
                  rows={[
                    [valueLabel, format(Number(payload[0].value))],
                    ...(extra && payload[0].payload.extra ? ([[extra, String(payload[0].payload.extra)]] as [string, string][]) : []),
                  ]}
                />
              ) : null
            }
          />
          <Bar dataKey="value" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
