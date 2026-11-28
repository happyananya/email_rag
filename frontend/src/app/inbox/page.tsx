"use client";

import { useEffect, useState } from "react";
import { EmailBody } from "@/components/EmailBody";
import { RichText } from "@/components/RichText";
import { api, type Account, type Email, type ThreadSummary } from "@/lib/api";

export default function InboxPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [threadId, setThreadId] = useState("");
  const [emails, setEmails] = useState<Email[]>([]);
  const [summary, setSummary] = useState("");
  const [draft, setDraft] = useState("");
  const [tone, setTone] = useState("professional");
  const [length, setLength] = useState("short");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [threadLoading, setThreadLoading] = useState(false);
  const [hasMoreThreads, setHasMoreThreads] = useState(false);

  useEffect(() => {
    api.accounts().then((a) => {
      setAccounts(a);
      if (a[0]) setAccountId(a[0].id);
    }).catch((e) => setError(e.message)).finally(() => setAccountsLoading(false));
  }, []);

  useEffect(() => {
    if (!accountId) return;
    setThreadId("");
    setThreads([]);
    setThreadsLoading(true);
    setError("");
    api.threads(accountId).then((rows) => {
      setThreads(rows);
      setHasMoreThreads(rows.length === 50);
    }).catch((e) => setError(e.message)).finally(() => setThreadsLoading(false));
  }, [accountId]);

  useEffect(() => {
    if (!threadId) return;
    setDraft("");
    setNotice("");
    setThreadLoading(true);
    api.thread(accountId, threadId).then((t) => {
      setEmails(t.emails);
      setSummary(t.summary?.content ?? "");
    }).catch((e) => setError(e.message)).finally(() => setThreadLoading(false));
  }, [accountId, threadId]);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function loadMoreThreads() {
    const cursor = threads.at(-1)?.sent_at;
    if (!cursor) {
      setHasMoreThreads(false);
      return;
    }
    setThreadsLoading(true);
    setError("");
    try {
      const rows = await api.threads(accountId, cursor);
      setThreads((current) => [...current, ...rows]);
      setHasMoreThreads(rows.length === 50);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setThreadsLoading(false);
    }
  }

  if (accountsLoading) {
    return <p className="muted" role="status">Loading your inbox…</p>;
  }

  if (accounts.length === 0) {
    return <p>No accounts yet. <a href="/accounts/">Connect Gmail</a> to get started.</p>;
  }

  return (
    <>
      <div className="row" style={{ marginBottom: 16 }}>
        <label>Inbox</label>
        <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.email_address}</option>
          ))}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="split">
        <ul className="list">
          {threads.map((t) => (
            <li key={t.thread_id} className={t.thread_id === threadId ? "active" : ""}
                onClick={() => setThreadId(t.thread_id)}>
              <div><strong>{t.subject || "(no subject)"}</strong></div>
              <div className="muted">{t.sender}</div>
              <div className="muted">{t.snippet}</div>
            </li>
          ))}
          {threads.length === 0 && !threadsLoading && <li className="muted">No emails synced yet.</li>}
          {threadsLoading && threads.length === 0 && <li className="muted" role="status">Loading emails…</li>}
          {hasMoreThreads && (
            <li className="list-action">
              <button type="button" disabled={threadsLoading} onClick={loadMoreThreads}>
                {threadsLoading ? "Loading…" : "Load more"}
              </button>
            </li>
          )}
        </ul>

        {threadId && (
          <section>
            {threadLoading && <p className="muted" role="status">Loading conversation…</p>}
            {!threadLoading && (
              <>
            <div className="panel">
              <div className="row">
                <button disabled={!!busy} onClick={() => run("summary", async () =>
                  setSummary((await api.summarize(accountId, threadId)).content))}>
                  {busy === "summary" ? "Summarizing…" : "Summarize"}
                </button>
                <button disabled={!!busy} onClick={() => run("actions", async () => {
                  const items = await api.extractActionItems(accountId, threadId);
                  setNotice(`${items.length} action item${items.length === 1 ? "" : "s"} added to your checklist.`);
                })}>
                  {busy === "actions" ? "Extracting…" : "Extract action items"}
                </button>
                <select value={tone} onChange={(e) => setTone(e.target.value)}>
                  {["professional", "friendly", "concise", "formal"].map((t) => <option key={t}>{t}</option>)}
                </select>
                <select value={length} onChange={(e) => setLength(e.target.value)}>
                  {["short", "medium", "long"].map((l) => <option key={l}>{l}</option>)}
                </select>
                <button disabled={!!busy} onClick={() => run("draft", async () =>
                  setDraft((await api.draft(accountId, threadId, tone, length)).content))}>
                  {busy === "draft" ? "Drafting…" : "Draft reply"}
                </button>
              </div>
            </div>
            {notice && <p className="notice" role="status">{notice}</p>}
            {summary && (
              <div className="panel">
                <h2 className="panel-title">Summary</h2>
                <RichText>{summary}</RichText>
              </div>
            )}
            {draft && (
              <div className="panel">
                <div className="row draft-header">
                  <strong>Draft reply</strong>
                  <button type="button" className="remove-button" onClick={() => setDraft("")}>
                    Remove draft
                  </button>
                </div>
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={10} style={{ width: "100%" }} />
              </div>
            )}
            {emails.map((m) => (
              <article key={m.id} className="email">
                <div><strong>{m.sender}</strong> <span className="muted">{m.sent_at && new Date(m.sent_at).toLocaleString()}</span></div>
                <div className="muted">{m.subject}</div>
                <EmailBody html={m.html_body} text={m.body} title={m.subject || "Email message"} />
                {m.attachments.length > 0 && <div className="muted">Attachments: {m.attachments.join(", ")}</div>}
              </article>
            ))}
              </>
            )}
          </section>
        )}
      </div>
    </>
  );
}
