"use client";

import { type FormEvent, useEffect, useState } from "react";
import { RichText } from "@/components/RichText";
import { api, type Account, type Source } from "@/lib/api";

export default function AskPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [accountsLoading, setAccountsLoading] = useState(true);

  useEffect(() => {
    api.accounts().then(setAccounts).catch((e) => setError(e.message)).finally(() => setAccountsLoading(false));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.ask(question, accountId || undefined);
      setAnswer(res.answer);
      setSources(res.sources);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Ask your inbox</h1>
      <form onSubmit={submit} className="row">
        <input style={{ flex: 1, minWidth: 240 }} value={question} onChange={(e) => setQuestion(e.target.value)}
               placeholder="e.g. When is the Q3 planning meeting and who is presenting?" />
        <select disabled={accountsLoading} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">{accountsLoading ? "Loading inboxes…" : "All inboxes"}</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.email_address}</option>)}
        </select>
        <button className="primary" disabled={busy}>{busy ? "Searching…" : "Ask"}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {answer && (
        <div className="panel" style={{ marginTop: 16 }}>
          <RichText>{answer}</RichText>
        </div>
      )}
      {sources.length > 0 && (
        <>
          <h3>Sources</h3>
          <ul className="list">
            {sources.filter((s) => s.cited).map((s) => (
              <li key={s.index}>
                <strong>[{s.index}] {s.subject || "(no subject)"}</strong>
                <div className="muted">{s.sender} · {s.sent_at && new Date(s.sent_at).toLocaleDateString()}</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
