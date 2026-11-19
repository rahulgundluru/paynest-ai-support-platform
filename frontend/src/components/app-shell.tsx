"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Badge, Button } from "@/components/ui";
import { hasPermission, useLogout } from "@/hooks/use-auth";
import type { Permission, User } from "@/types/api";

interface NavItem {
  label: string;
  href?: string; // absent = module not built yet; rendered as a non-interactive roadmap entry
  phase?: number;
  permission?: Permission;
}

const NAV: NavItem[] = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Tickets", href: "/tickets", permission: "tickets:read" },
  { label: "Processing monitor", href: "/processing", permission: "tickets:read" },
  { label: "Customers", href: "/customers", permission: "customers:read" },
  { label: "Incidents & duplicates", href: "/incidents", permission: "tickets:read" },
  { label: "Knowledge base", href: "/knowledge", permission: "knowledge:read" },
  { label: "Review queue", href: "/review", permission: "approvals:read" },
  { label: "Evaluations", phase: 6 },
  { label: "Cost analytics", phase: 6 },
  { label: "Data ingestion", href: "/ingestion", permission: "ingestion:read" },
  { label: "Audit log", href: "/audit", permission: "audit:read" },
  { label: "Settings", href: "/settings", permission: "settings:read" },
];

export function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const logout = useLogout();
  const [open, setOpen] = useState(false);

  const items = NAV.filter((item) => !item.permission || hasPermission(user, item.permission));

  return (
    <div className="min-h-screen md:flex">
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3 md:hidden">
        <span className="font-semibold">PayNest</span>
        <Button variant="secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="sidebar">
          Menu
        </Button>
      </header>
      <aside
        id="sidebar"
        className={`${open ? "block" : "hidden"} w-full border-b border-border bg-surface md:block md:min-h-screen md:w-60 md:shrink-0 md:border-r md:border-b-0`}
      >
        <div className="hidden px-5 py-4 md:block">
          <p className="font-semibold">PayNest</p>
          <p className="text-xs text-text-muted">Support Intelligence</p>
        </div>
        <nav aria-label="Main" className="px-2 pb-4">
          <ul className="space-y-0.5">
            {items.map((item) =>
              item.href ? (
                <li key={item.label}>
                  <Link
                    href={item.href}
                    onClick={() => setOpen(false)}
                    aria-current={pathname.startsWith(item.href) ? "page" : undefined}
                    className={`block rounded-md px-3 py-2 text-sm ${
                      pathname.startsWith(item.href)
                        ? "bg-surface-muted font-medium text-text"
                        : "text-text-muted hover:bg-surface-muted hover:text-text"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              ) : (
                <li key={item.label} className="flex items-center justify-between px-3 py-2 text-sm text-text-muted/70">
                  <span>{item.label}</span>
                  <Badge>Phase {item.phase}</Badge>
                </li>
              ),
            )}
          </ul>
        </nav>
      </aside>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-end gap-3 border-b border-border bg-surface px-4 py-2 md:px-6">
          <span className="text-sm text-text-muted">
            {user.full_name} · {user.regions.join(" / ")}
          </span>
          <Button
            variant="secondary"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login") })}
          >
            Sign out
          </Button>
        </div>
        <main className="mx-auto max-w-6xl px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  );
}
