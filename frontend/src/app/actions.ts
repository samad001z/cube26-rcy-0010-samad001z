"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  BackendError,
  COOKIE_MAX_AGE,
  KEY_COOKIE,
  ORG_COOKIE,
  callBackend,
  currentKey,
  discoverOrg,
} from "@/lib/api";

export interface FormState {
  error: string | null;
  ok?: string | null;
}

export async function login(_prev: FormState, form: FormData): Promise<FormState> {
  const key = String(form.get("key") ?? "").trim();
  if (!key) return { error: "Paste the API key for your organisation." };
  try {
    // A key is valid when the backend accepts it; nothing about it is checked here.
    await callBackend(key, "/runs");
  } catch (err) {
    if (err instanceof BackendError && err.status === 401) {
      return { error: "That key was not accepted." };
    }
    return { error: err instanceof Error ? err.message : "The backend could not be reached." };
  }
  const jar = await cookies();
  const options = {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: COOKIE_MAX_AGE,
  } as const;
  jar.set(KEY_COOKIE, key, options);
  const org = await discoverOrg(key);
  if (org) jar.set(ORG_COOKIE, org, options);
  else jar.delete(ORG_COOKIE);
  redirect("/");
}

export async function logout(): Promise<void> {
  const jar = await cookies();
  jar.delete(KEY_COOKIE);
  jar.delete(ORG_COOKIE);
  redirect("/login");
}

export async function overrideDecision(_prev: FormState, form: FormData): Promise<FormState> {
  const key = await currentKey();
  if (!key) redirect("/login");
  const recordId = String(form.get("record_id") ?? "");
  const payload = {
    new_decision: String(form.get("new_decision") ?? ""),
    reason: String(form.get("reason") ?? "").trim(),
    reviewer: String(form.get("reviewer") ?? "").trim(),
  };
  if (!payload.new_decision) return { error: "Choose the new decision." };
  if (payload.reason.length < 3) return { error: "Write the reason for the override." };
  if (!payload.reviewer) return { error: "Enter your name as the reviewer." };
  try {
    await callBackend(key, `/decisions/${encodeURIComponent(recordId)}/overrides`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    if (err instanceof BackendError && err.status === 401) redirect("/login?expired=1");
    return { error: err instanceof Error ? err.message : "The override was not saved." };
  }
  revalidatePath(`/decisions/${recordId}`);
  revalidatePath("/");
  return { error: null, ok: `Saved: now ${payload.new_decision.replaceAll("_", " ")}.` };
}
