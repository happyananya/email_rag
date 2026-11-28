"use client";

import { useEffect, useState } from "react";
import { api, type Account } from "@/lib/api";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    return api.accounts().then(setAccounts).catch((e) => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);

  async function connect() {
    setBusy("connect");
    setError("");
    try {
      const state = crypto.randomUUID();
      sessionStorage.setItem("oauth_state", state);
      const { auth_url } = await api.connectGmail(state);
      window.location.href = auth_url;
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  }

  async function disconnect(a: Account) {
    if (!confirm(`Disconnect ${a.email_address}? All synced mail and AI results will be deleted.`)) return;
    setBusy(a.id);
    setError("");
    try {
      await api.disconnect(a.id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <h1>Connected accounts</h1>
      {error && <p className="error">{error}</p>}
      <ul className="list">
        {accounts.map((a) => (
          <li key={a.id} className="row">
            <span>{a.email_address}</span>
            <span className="muted">
              {a.provider} · {a.status}
              {a.last_synced_at && ` · synced ${new Date(a.last_synced_at).toLocaleString()}`}
            </span>
            <span className="spacer" />
            <button disabled={!!busy} onClick={() => disconnect(a)}>
              {busy === a.id ? "Disconnecting…" : "Disconnect"}
            </button>
          </li>
        ))}
        {loading && <li className="muted" role="status">Loading accounts…</li>}
        {!loading && accounts.length === 0 && <li className="muted">No accounts connected yet.</li>}
      </ul>
      <p>
        <button className="primary" disabled={!!busy} onClick={connect}>
          {busy === "connect" ? "Connecting…" : "Connect Gmail"}
        </button>
      </p>
    </>
  );
}
