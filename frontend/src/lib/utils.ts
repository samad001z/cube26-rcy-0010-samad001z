import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** snake_case or UPPER_CASE value to words: "DO_NOT_CLAIM" -> "DO NOT CLAIM". */
export function words(v: string): string {
  return v.replaceAll("_", " ");
}

/** "inbound_defect_fee" -> "Inbound defect fee". */
export function sentence(v: string): string {
  const w = words(v).toLowerCase();
  return w.charAt(0).toUpperCase() + w.slice(1);
}

export function dateTime(iso: string): string {
  return (
    new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC"
  );
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { dateStyle: "medium", timeZone: "UTC" });
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

/**
 * Orders two non-negative decimal strings from the backend ("12.50" vs "4.25") without
 * turning them into floats. Only for sorting rows; no amount is ever computed here.
 */
export function compareDecimal(a: string | null, b: string | null): number {
  if (a === b) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  const [ai, af = ""] = a.split(".");
  const [bi, bf = ""] = b.split(".");
  const ia = ai.replace(/^0+(?=\d)/, "");
  const ib = bi.replace(/^0+(?=\d)/, "");
  if (ia.length !== ib.length) return ia.length - ib.length;
  if (ia !== ib) return ia < ib ? -1 : 1;
  const len = Math.max(af.length, bf.length);
  const fa = af.padEnd(len, "0");
  const fb = bf.padEnd(len, "0");
  return fa === fb ? 0 : fa < fb ? -1 : 1;
}
