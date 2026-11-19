/**
 * Same-origin proxy to the FastAPI backend.
 *
 * The browser only ever talks to the Next.js origin, so the backend's httpOnly session
 * cookie works without cross-site cookie settings. API_INTERNAL_URL is read at request
 * time (not baked into the build), so one image runs in every environment.
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const FORWARD_REQUEST_HEADERS = ["authorization", "content-type", "cookie", "x-request-id", "accept"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "set-cookie", "x-request-id", "www-authenticate"];

function backendUrl(path: string[], search: string): string {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  return `${base.replace(/\/$/, "")}/api/${path.map(encodeURIComponent).join("/")}${search}`;
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(backendUrl(path, request.nextUrl.search), {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return NextResponse.json(
      { error: { code: "backend_unreachable", message: "The API service is not reachable", request_id: null } },
      { status: 502 },
    );
  }
  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    if (name === "set-cookie") {
      for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
    } else {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
  }
  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  return new NextResponse(body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
