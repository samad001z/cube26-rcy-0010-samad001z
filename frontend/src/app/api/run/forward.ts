import "server-only";

import { COOKIE_MAX_AGE, ORG_COOKIE, backendUrl } from "@/lib/api";

/**
 * Sends an upload to POST /agent with the operator's key and relays the answer. The backend
 * checks file names, sizes and the organisation; nothing is decided here. The response names
 * the organisation, so the top bar's org cookie is refreshed from it.
 */
export async function forwardToAgent(key: string, form: FormData): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${backendUrl()}/agent`, {
      method: "POST",
      headers: { "X-API-Key": key },
      body: form,
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "the Alibi backend could not be reached" }, { status: 503 });
  }
  const body = await res.text();
  const headers = new Headers({
    "Content-Type": res.headers.get("Content-Type") ?? "application/json",
    "X-Alibi-Run-Id": res.headers.get("X-Alibi-Run-Id") ?? "",
  });
  const org = res.headers.get("X-Alibi-Organization");
  if (res.ok && org) {
    const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
    headers.append(
      "Set-Cookie",
      `${ORG_COOKIE}=${encodeURIComponent(org)}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; SameSite=Strict${secure}`,
    );
  }
  return new Response(body, { status: res.status, headers });
}
