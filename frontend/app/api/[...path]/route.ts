const REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "cookie",
  "origin",
  "user-agent",
  "x-csrf-token",
  "x-request-id",
] as const;

const DEFAULT_UPSTREAM_TIMEOUT_MS = 30_000;
const LLM_UPSTREAM_TIMEOUT_MS = 195_000;
const DEFAULT_MAX_REQUEST_BODY_BYTES = 256 * 1024;
const NO_STORE = "private, no-store, max-age=0, must-revalidate";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function apiUpstream() {
  return (
    process.env.MVP_INTERNAL_API_BASE_URL ?? "http://127.0.0.1:8787"
  ).replace(/\/+$/, "");
}

function upstreamTimeout(path: string[]) {
  const resource = path.join("/");
  const invokesLlm =
    /^v1\/ai\/(?:chat|configuration\/test)$/.test(resource) ||
    resource === "v1/weekly-reports/current/generate" ||
    resource === "v1/dashboard/team-summary";
  return invokesLlm ? LLM_UPSTREAM_TIMEOUT_MS : DEFAULT_UPSTREAM_TIMEOUT_MS;
}

function maxRequestBodyBytes() {
  const configured = Number(process.env.MVP_MAX_REQUEST_BODY_BYTES);
  return Number.isSafeInteger(configured) && configured > 0
    ? configured
    : DEFAULT_MAX_REQUEST_BODY_BYTES;
}

async function readBodyWithLimit(request: Request): Promise<ArrayBuffer | null> {
  if (request.method === "GET" || request.method === "HEAD" || !request.body) {
    return null;
  }

  const limit = maxRequestBodyBytes();
  const declaredLength = request.headers.get("content-length");
  if (declaredLength && Number(declaredLength) > limit) {
    throw new RangeError("request body exceeds configured limit");
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        throw new RangeError("request body exceeds configured limit");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return merged.buffer;
}

function secureResponseHeaders(headers = new Headers()) {
  headers.set("cache-control", NO_STORE);
  headers.set("content-security-policy", "default-src 'none'; frame-ancestors 'none'");
  headers.set("referrer-policy", "no-referrer");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-frame-options", "DENY");
  return headers;
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
  // The Fetch Request API does not expose a trustworthy socket peer address.
  // Deliberately omit client-supplied forwarding headers so the API observes
  // only the frontend proxy's transport address.
  headers.set("x-forwarded-host", requestUrl.host);
  headers.set("x-forwarded-proto", requestUrl.protocol.slice(0, -1));

  let body: ArrayBuffer | null;
  try {
    body = await readBodyWithLimit(request);
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    return Response.json(
      {
        code: "REQUEST_BODY_TOO_LARGE",
        message: "请求内容过大",
        request_id: request.headers.get("x-request-id"),
        details: { max_bytes: maxRequestBodyBytes() },
      },
      { status: 413, headers: secureResponseHeaders() },
    );
  }

  try {
    const upstreamResponse = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: body?.byteLength ? body : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(upstreamTimeout(path)),
    });
    const responseHeaders = secureResponseHeaders(
      new Headers(upstreamResponse.headers),
    );
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return Response.json(
      {
        code: timedOut ? "API_UPSTREAM_TIMEOUT" : "API_UPSTREAM_UNAVAILABLE",
        message: timedOut
          ? "系统服务处理时间较长，请稍后确认结果或重试"
          : "暂时无法连接系统服务，请稍后重试",
        request_id: null,
        details: null,
      },
      {
        status: timedOut ? 504 : 502,
        headers: secureResponseHeaders(),
      },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
