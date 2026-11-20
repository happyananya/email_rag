"use client";

import { useEffect, useState } from "react";
import { api, type Account } from "@/lib/api";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");

  const load = () => api.accounts().then(setAccounts).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function connect() {
    const state = crypto.randomUUID();
    sessionStorage.setItem("oauth_state", state);
    const { auth_url } = await api.connectGmail(state);
    window.location.href = auth_url;
  }

  async function disconnect(a: Account) {
    if (!confirm(`Disconnect ${a.email_address}? All synced mail and AI results will be deleted.`)) return;
    await api.disconnect(a.id);
    load();
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
            <button onClick={() => disconnect(a)}>Disconnect</button>
          </li>
        ))}
        {accounts.length === 0 && <li className="muted">No accounts connected yet.</li>}
      </ul>
      <p>
        <button className="primary" onClick={connect}>
          Connect Gmail
        </button>
      </p>
    </>
  );
}
