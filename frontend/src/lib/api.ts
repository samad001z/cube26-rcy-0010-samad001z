import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// The API key lives only in an httpOnly cookie and is sent to the backend from the server.
// Browser JavaScript never sees it.
export const KEY_COOKIE = "alibi_key";
// The organisation the key belongs to, for the top bar only. No endpoint returns it yet
// (backlog: GET /me), so it is read from a decision record at sign-in or after a run.
export const ORG_COOKIE = "alibi_org";
export const COOKIE_MAX_AGE = 60 * 60 * 8;

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

export async function currentOrg(): Promise<string | undefined> {
  return (await cookies()).get(ORG_COOKIE)?.value;
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

/**
 * The organisation of `key`, read from its newest decision record; undefined when the
 * organisation has no run yet. Workaround until the backend has GET /me.
 */
export async function discoverOrg(key: string): Promise<string | undefined> {
  try {
    const list = await callBackend<{ items: { record_id: string }[] }>(key, "/decisions");
    const first = list.items[0];
    if (!first) return undefined;
    const d = await callBackend<{ record: { organization_id: string } }>(
      key,
      `/decisions/${encodeURIComponent(first.record_id)}`,
    );
    return d.record.organization_id;
  } catch {
    return undefined;
  }
}
