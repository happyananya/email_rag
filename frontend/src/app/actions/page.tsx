"use client";

import { useEffect, useState } from "react";
import { api, type ActionItem } from "@/lib/api";

export default function ActionItemsPage() {
  const [items, setItems] = useState<ActionItem[]>([]);
  const [showDone, setShowDone] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    api.actionItems(showDone ? undefined : "open").then(setItems).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [showDone]);

  async function toggle(item: ActionItem) {
    setBusyId(item.id);
    setError("");
    try {
      const updated = await api.setActionItemStatus(item.id, item.status === "open" ? "done" : "open");
      setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <>
      <h1>Action items</h1>
      <label className="row">
        <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Show completed
      </label>
      {error && <p className="error">{error}</p>}
      <ul className="list" style={{ marginTop: 12 }}>
        {items.map((i) => (
          <li key={i.id} className="row" aria-busy={busyId === i.id} onClick={() => !busyId && toggle(i)}>
            <input type="checkbox" readOnly disabled={!!busyId} checked={i.status === "done"} />
            <span style={{ textDecoration: i.status === "done" ? "line-through" : undefined }}>{i.description}</span>
            <span className="spacer" />
            <span className="muted">{i.owner ?? ""}{i.due_date ? ` · due ${i.due_date}` : ""}</span>
          </li>
        ))}
        {loading && <li className="muted" role="status">Loading action items…</li>}
        {!loading && items.length === 0 && <li className="muted">Nothing here. Extract action items from a thread in your inbox.</li>}
      </ul>
    </>
  );
}
