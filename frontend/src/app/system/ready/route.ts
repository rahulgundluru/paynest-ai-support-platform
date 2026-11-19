/** Proxies the backend readiness probe so the UI can show real system status. */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const upstream = await fetch(`${base.replace(/\/$/, "")}/ready`, { cache: "no-store" });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { status: "unavailable", checks: { api: "unreachable" } },
      { status: 503 },
    );
  }
}
