import type { NextRequest } from "next/server";

import { KEY_COOKIE } from "@/lib/api";

import { forwardToAgent } from "./forward";

// Forwards the operator's upload to POST /agent with the key from the httpOnly cookie.
export async function POST(request: NextRequest) {
  const key = request.cookies.get(KEY_COOKIE)?.value;
  if (!key) return Response.json({ detail: "not signed in" }, { status: 401 });
  return forwardToAgent(key, await request.formData());
}
