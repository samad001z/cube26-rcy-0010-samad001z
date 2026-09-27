/** The backend's `detail` from an error response, as one line. */
export async function readError(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  return `${res.status}: ${detail}`;
}
