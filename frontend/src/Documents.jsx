import { useEffect, useState } from "react";
import { errorMessage } from "./errors";

const API_BASE = "/api";
// Session key written by App.jsx (see saveAuth in App.jsx).
const TOKEN_KEY = "ai_kb_token";

// Employee-facing roles accepted by the backend (document ingestion, FR02).
export const ROLES = ["employee", "hr", "manager"];
export const ROLE_LABELS = {
  employee: "Employee",
  hr: "HR",
  manager: "Manager",
};

// ---------------------------------------------------------------------------
// Authenticated multipart helper shared by upload (POST) and update (PUT).
//
// IMPORTANT: we must NOT set the `Content-Type` header here — fetch adds the
// required `multipart/form-data; boundary=...` automatically. The `apiFetch`
// helper in App.jsx always forces JSON, so document uploads use this dedicated
// JSON-free path. Authorization uses the persisted Bearer token; the backend
// additionally requires administrator permission (403 otherwise).
// ---------------------------------------------------------------------------
async function _multipartRequest({ path, method, file, allowedRoles, onExpired }) {
  const form = new FormData();
  form.append("file", file);
  form.append("allowed_roles", allowedRoles.join(","));

  const token = localStorage.getItem(TOKEN_KEY) || null;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (res.status === 401) {
    onExpired?.();
    throw new Error("Session expired. Please sign in again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      errorMessage(
        data,
        res.status,
        `Document ${method === "PUT" ? "update" : "upload"} failed (${res.status})`,
      ),
    );
  }
  return data;
}

/**
 * Upload a brand-new document (admin only).
 * @param {File} file          The PDF/DOCX to ingest.
 * @param {string[]} allowedRoles Roles that may access it (subset of ROLES).
 * @param {() => void} [onExpired] Called when the session token is rejected.
 */
export async function uploadDocument(file, allowedRoles, onExpired) {
  return _multipartRequest({
    path: "/documents/upload",
    method: "POST",
    file,
    allowedRoles,
    onExpired,
  });
}

/**
 * Replace the content of an existing document (admin only).
 * The backend clears the old indexed chunks, re-ingests the new file and
 * updates the document record.
 * @param {number} documentId  The document record to update.
 * @param {File} file          The replacement PDF/DOCX.
 * @param {string[]} allowedRoles Roles that may access it.
 * @param {() => void} [onExpired] Called when the session token is rejected.
 */
export async function replaceDocument(documentId, file, allowedRoles, onExpired) {
  return _multipartRequest({
    path: `/documents/${documentId}`,
    method: "PUT",
    file,
    allowedRoles,
    onExpired,
  });
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Administrator document manager.
 *
 * Combines uploading new documents and updating (replacing) existing ones in a
 * single form. Authorization is enforced twice: the panel is only mounted when
 * the logged-in user is an admin, and the backend rejects unprivileged requests
 * with 403. A 401 (expired/deactivated session) triggers the passed onExpired
 * callback so the app can sign the user out.
 */
export default function Documents({ onExpired }) {
  const [mode, setMode] = useState("upload"); // "upload" | "replace"
  const [file, setFile] = useState(null);
  const [allowedRoles, setAllowedRoles] = useState(() => new Set(["employee"]));
  const [documents, setDocuments] = useState([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  // Load the existing document list whenever the admin switches to update mode.
  useEffect(() => {
    if (mode !== "replace") {
      setResult(null);
      return;
    }
    let cancelled = false;
    setDocumentsLoading(true);
    setError("");
    const token = localStorage.getItem(TOKEN_KEY) || null;
    fetch(`${API_BASE}/documents`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => {
        if (res.status === 401) {
          onExpired?.();
          throw new Error("Session expired. Please sign in again.");
        }
        if (!res.ok) {
          throw new Error(errorMessage({}, res.status, `Could not load documents (${res.status})`));
        }
        return res.json();
      })
      .then((list) => {
        if (!cancelled) {
          setDocuments(Array.isArray(list) ? list : []);
        }
      })
      .catch((err) => {
        if (!cancelled && err.message !== "Session expired. Please sign in again.") {
          setError(err.message || "Could not load the document list.");
        }
      })
      .finally(() => {
        if (!cancelled) setDocumentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  function toggleRole(role) {
    const next = new Set(allowedRoles);
    if (next.has(role)) next.delete(role);
    else next.add(role);
    setAllowedRoles(next);
  }

  function switchMode(nextMode) {
    if (nextMode === mode) return;
    setMode(nextMode);
    setFile(null);
    setResult(null);
    setError("");
    setSelectedId("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setResult(null);

    const roles = ROLES.filter((role) => allowedRoles.has(role));
    if (!file) {
      setError("Choose a PDF or DOCX file to upload.");
      return;
    }
    if (roles.length === 0) {
      setError("Select at least one role that may access this document.");
      return;
    }
    if (mode === "replace" && !selectedId) {
      setError("Pick the existing document you want to update.");
      return;
    }

    setLoading(true);
    try {
      const data =
        mode === "upload"
          ? await uploadDocument(file, roles, onExpired)
          : await replaceDocument(selectedId, file, roles, onExpired);
      setResult(data);
      setFile(null);
      // Refresh the list so the updated record (new size/roles) stays current.
      setDocuments((prev) => prev.map((d) => (d.id === data.document.id ? data.document : d)));
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  const roles = ROLES.filter((role) => allowedRoles.has(role));
return (
    <section className="doc-manager" aria-label="Document manager">
      <h2>Document manager</h2>
      <p className="doc-manager-note">
        Upload new PDF/DOCX knowledge documents or update (replace) existing ones.
      </p>

      <div className="doc-mode-tabs" role="tablist" aria-label="Action">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "upload"}
          className={mode === "upload" ? "doc-mode-tab active" : "doc-mode-tab"}
          onClick={() => switchMode("upload")}
        >
          Upload new
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "replace"}
          className={mode === "replace" ? "doc-mode-tab active" : "doc-mode-tab"}
          onClick={() => switchMode("replace")}
        >
          Update existing
        </button>
      </div>

      <form className="doc-form" onSubmit={handleSubmit}>
        {mode === "replace" && (
          <div className="doc-field">
            <label htmlFor="doc-target">Document to update</label>
            {documentsLoading ? (
              <p className="doc-hint">Loading documents…</p>
            ) : documents.length === 0 ? (
              <p className="doc-hint">
                No updateable documents found for your role. Upload one first.
              </p>
            ) : (
              <select
                id="doc-target"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                required
                disabled={loading}
              >
                <option value="">— Select a document —</option>
                {documents.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {doc.document_name} ({doc.allowed_roles.join(", ")} ·{" "}
                    {formatBytes(doc.file_size)})
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        <div className="doc-field">
          <label htmlFor="doc-file">
            {mode === "upload" ? "New document" : "Replacement document"}
          </label>
          <input
            id="doc-file"
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            disabled={loading || (mode === "replace" && documentsLoading)}
          />
          {file && (
            <p className="doc-hint">
              {file.name} · {formatBytes(file.size)}
            </p>
          )}
        </div>

        <fieldset className="doc-roles">
          <legend>Who may access this document?</legend>
          {ROLES.map((role) => {
            const checked = allowedRoles.has(role);
            return (
              <label key={role} className={checked ? "doc-role-checked" : ""}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleRole(role)}
                  disabled={loading || (mode === "replace" && documentsLoading)}
                />
                {ROLE_LABELS[role]}
              </label>
            );
          })}
        </fieldset>

        {error && (
          <p className="doc-error" role="alert">
            {error}
          </p>
        )}

        {result && (
          <div className="doc-result" role="status">
            <strong>
              {mode === "upload" ? "Uploaded" : "Updated"}{" "}
              {result.document?.document_name}:
            </strong>{" "}
            {result.chunk_count} chunk{result.chunk_count === 1 ? "" : "s"} indexed
            {result.sections && result.sections.length > 0
              ? ` (${result.sections.join(", ")})`
              : ""}.
          </div>
        )}

        <button
          type="submit"
          className="doc-submit"
          disabled={
            loading ||
            !file ||
            roles.length === 0 ||
            (mode === "replace" && (!selectedId || documentsLoading))
          }
        >
          {loading
            ? (mode === "upload" ? "Uploading…" : "Updating…")
            : mode === "upload"
              ? "Upload document"
              : "Update document"}
        </button>
      </form>
    </section>
  );
}