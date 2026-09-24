/**
 * Normalize a FastAPI error body into a readable message.
 *
 * FastAPI puts a plain string in `detail` for HTTPException, but a *list* of
 * error objects for 422 validation failures. Passing that list straight to
 * `new Error(...)` renders as "[object Object]", so both shapes are handled
 * here.
 */
export function errorMessage(data, status, fallback) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => item?.msg).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback || `Request failed (${status})`;
}
