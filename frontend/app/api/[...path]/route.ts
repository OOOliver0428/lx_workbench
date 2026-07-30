const REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "cookie",
  "origin",
  "user-agent",
  "x-csrf-token",
  "x-forwarded-for",
  "x-request-id",
] as const;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function apiUpstream() {
  return (
    process.env.MVP_INTERNAL_API_BASE_URL ?? "http://127.0.0.1:8787"
  ).replace(/\/+$/, "");
}

async function proxy(request: Request, context: RouteContext) {
  const { path } = await context.params;
  const requestUrl = new URL(request.url);
  const targetUrl = new URL(
    `/api/${path.map((segment) => encodeURIComponent(segment)).join("/")}`,
    `${apiUpstream()}/`,
  );
  targetUrl.search = requestUrl.search;

  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("x-forwarded-host", requestUrl.host);
  headers.set("x-forwarded-proto", requestUrl.protocol.slice(0, -1));

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const body = hasBody ? await request.arrayBuffer() : null;

  try {
    const upstreamResponse = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: body?.byteLength ? body : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(30_000),
    });
    const responseHeaders = new Headers(upstreamResponse.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      {
        code: "API_UPSTREAM_UNAVAILABLE",
        message: "暂时无法连接系统服务，请稍后重试",
        request_id: null,
        details: null,
      },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
