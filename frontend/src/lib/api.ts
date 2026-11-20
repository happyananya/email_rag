import { fetchAuthSession } from "aws-amplify/auth";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export type Account = {
  id: string;
  provider: string;
  email_address: string;
  status: string;
  last_synced_at: string | null;
};
export type ThreadSummary = {
  thread_id: string;
  email_id: string;
  subject: string | null;
  sender: string | null;
  sent_at: string | null;
  snippet: string | null;
};
export type Email = {
  id: string;
  subject: string | null;
  sender: string | null;
  recipients: string[];
  sent_at: string | null;
  body: string;
  attachments: string[];
};
export type ActionItem = {
  id: string;
  account_id: string;
  thread_id: string;
  description: string;
  owner: string | null;
  due_date: string | null;
  status: "open" | "done";
};
export type Source = {
  index: number;
  email_id: string;
  account_id: string;
  thread_id: string;
  subject: string | null;
  sender: string | null;
  sent_at: string | null;
  score: number;
  cited: boolean;
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { tokens } = await fetchAuthSession();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: tokens?.idToken?.toString() ?? "",
      ...init.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.message ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown = {}) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  accounts: () => request<Account[]>("/accounts"),
  connectGmail: (state: string) => post<{ auth_url: string }>("/accounts/gmail/connect", { state }),
  gmailCallback: (code: string) => post<Account>("/accounts/gmail/callback", { code }),
  disconnect: (id: string) => request<{ deleted: string }>(`/accounts/${id}`, { method: "DELETE" }),

  threads: (accountId: string) => request<ThreadSummary[]>(`/accounts/${accountId}/threads`),
  thread: (accountId: string, threadId: string) =>
    request<{ emails: Email[]; summary: { content: string } | null }>(
      `/accounts/${accountId}/threads/${threadId}`,
    ),
  summarize: (accountId: string, threadId: string) =>
    post<{ content: string }>(`/accounts/${accountId}/threads/${threadId}/summary`),
  draft: (accountId: string, threadId: string, tone: string, length: string, instructions = "") =>
    post<{ content: string }>(`/accounts/${accountId}/threads/${threadId}/draft`, {
      tone,
      length,
      instructions,
    }),
  extractActionItems: (accountId: string, threadId: string) =>
    post<ActionItem[]>(`/accounts/${accountId}/threads/${threadId}/action-items`),

  actionItems: (status?: "open" | "done") =>
    request<ActionItem[]>(`/action-items${status ? `?status=${status}` : ""}`),
  setActionItemStatus: (id: string, status: "open" | "done") =>
    request<ActionItem>(`/action-items/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),

  ask: (question: string, accountId?: string) =>
    post<{ answer: string; sources: Source[] }>("/ask", { question, account_id: accountId }),
};
