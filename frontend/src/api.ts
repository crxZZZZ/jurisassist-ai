export type User = { id: string; name: string; email: string; role: string };
export type Citation = {
  id: string;
  document_id: string;
  title: string;
  locator: string;
  text: string;
  kind: string;
  url?: string;
  version: string;
  collected_at: string;
  checked_at?: string;
};
export type Claim = { text: string; citation_ids: string[] };
export type Finding = {
  title: string;
  detail: string;
  priority: "low" | "medium" | "high";
  contract_chunk_id: string;
  quote: string;
  citation_ids: string[];
  checklist: string;
};
export type Basis = {
  indexed_sources: number;
  expected_sources: number;
  pending_update: boolean;
  stale: boolean;
  warning?: string;
};
export type Answer = {
  status?: string;
  summary: string;
  claims?: Claim[];
  questions?: string[];
  citations: Citation[];
  basis?: Basis;
  model?: string;
  prompt_version?: string;
  findings?: Finding[];
  obligations?: Claim[];
  deadlines?: Claim[];
  coverage?: { processed_chunks: number; total_chunks: number };
};
export type Message = {
  id: string;
  role: string;
  content: string;
  evidence: Answer;
  created_at: string;
};
export type Conversation = { id: string; title: string; created_at?: string };
export type Doc = {
  id: string;
  title: string;
  kind: string;
  status: string;
  version: string;
  source_id?: string;
  created_at: string;
  approved_at?: string;
  review_note?: string;
  chunk_count: number;
  url?: string;
  body?: string;
};
export type Job = {
  id: string;
  kind: string;
  status: string;
  stage: string;
  attempts: number;
  error?: string;
  result: Record<string, unknown>;
  created_at: string;
  conversation_id?: string;
};
export type Review = { item_index: number; decision: string; note: string };
export type Analysis = {
  id: string;
  document_id: string;
  result: Answer;
  reviews: Review[];
};
export type AnalysisList = {
  id: string;
  document_id: string;
  title: string;
  created_at: string;
};
export type Source = {
  id: string;
  title: string;
  url: string;
  checked_at?: string;
  check_error?: string;
};
export type Status = {
  ollama_online: boolean;
  model_installed: boolean;
  model: string;
  basis: Basis;
  worker_busy: boolean;
};
export type Experiment = {
  id: string;
  mode: string;
  prompt_version: string;
  recall_at_5: number | null;
  evaluated: number;
  created_at: string;
  model?: string;
  generation?: boolean;
};
export type Overview = {
  jobs: Job[];
  feedback: { rating: number; comment: string; message_id: string }[];
  evaluations: Experiment[];
  basis: Basis;
};

let csrf = "";
export function setCsrf(token: string) {
  csrf = token;
}
function csrfCookie() {
  return (
    document.cookie
      .split("; ")
      .find((v) => v.startsWith("juris_csrf="))
      ?.split("=")[1] || ""
  );
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (options.method && !["GET", "HEAD"].includes(options.method))
    headers.set("X-CSRF-Token", csrf || csrfCookie());
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : "Confira os campos e tente novamente.";
    if (response.status === 401 && path !== "/auth/login")
      window.dispatchEvent(new Event("session-expired"));
    throw new Error(detail);
  }
  return response.json();
}
export function post<T>(path: string, data?: unknown) {
  return api<T>(path, {
    method: "POST",
    body: data === undefined ? undefined : JSON.stringify(data),
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}
export function date(value?: string) {
  return value
    ? new Date(value.endsWith("Z") ? value : value + "Z").toLocaleDateString(
        "pt-BR",
      )
    : "Ainda não verificado";
}
export const statusLabel: Record<string, string> = {
  pending: "Aguardando indexação",
  pending_review: "Aguardando revisão",
  indexing: "Indexando",
  indexed: "Fonte ativa",
  ready: "Pronto para análise",
  retired: "Versão anterior",
  superseded: "Versão substituída",
  queued: "Na fila",
  running: "Em andamento",
  completed: "Concluído",
  failed: "Falhou",
};
