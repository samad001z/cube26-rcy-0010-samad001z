import type { NextRequest } from "next/server";

import { KEY_COOKIE, backendUrl } from "@/lib/api";

// Forwards the operator's upload to POST /agent with the key from the httpOnly cookie.
// The backend checks file names, sizes and the organisation; nothing is decided here.
export async function POST(request: NextRequest) {
  const key = request.cookies.get(KEY_COOKIE)?.value;
  if (!key) return Response.json({ detail: "not signed in" }, { status: 401 });
  const form = await request.formData();
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
  return new Response(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("Content-Type") ?? "application/json",
      "X-Alibi-Run-Id": res.headers.get("X-Alibi-Run-Id") ?? "",
    },
  });
}
