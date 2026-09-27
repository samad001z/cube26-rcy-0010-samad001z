import "server-only";

import { backendUrl } from "@/lib/api";

/**
 * Sends an upload to POST /agent with the operator's key and relays the answer. The backend
 * checks file names, sizes and the organisation; nothing is decided here.
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
  return new Response(body, { status: res.status, headers });
}
