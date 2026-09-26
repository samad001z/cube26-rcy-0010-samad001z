import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// The API key lives only in an httpOnly cookie and is sent to the backend from the server.
// Browser JavaScript never sees it.
export const KEY_COOKIE = "alibi_key";

export function backendUrl(): string {
  return (process.env.ALIBI_BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export class BackendError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
        .join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return res.statusText;
  }
}

export async function currentKey(): Promise<string | undefined> {
  return (await cookies()).get(KEY_COOKIE)?.value;
}

/** Call the backend with an explicit key. Throws BackendError on a non-2xx answer. */
export async function callBackend<T>(key: string, path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${backendUrl()}${path}`, {
      ...init,
      cache: "no-store",
      headers: { ...(init.headers ?? {}), "X-API-Key": key },
    });
  } catch {
    throw new BackendError(503, "the Alibi backend could not be reached");
  }
  if (!res.ok) throw new BackendError(res.status, await detail(res));
  return (await res.json()) as T;
}

/** For pages: no key or a rejected key sends the operator to the login page. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const key = await currentKey();
  if (!key) redirect("/login");
  try {
    return await callBackend<T>(key, path, init);
  } catch (err) {
    if (err instanceof BackendError && err.status === 401) redirect("/login?expired=1");
    throw err;
  }
}
