import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  Clock3,
  ExternalLink,
  FileCheck2,
  FileText,
  FolderOpen,
  Layers3,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  Plus,
  Scale,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Upload,
  X,
} from "lucide-react";
import {
  api,
  post,
  setCsrf,
  date,
  statusLabel,
  type User,
  type Citation,
  type Message,
  type Conversation,
  type Doc,
  type Job,
  type Analysis,
  type AnalysisList,
  type Source,
  type Status,
  type Overview,
  type Finding,
  type Review,
  type Answer,
} from "./api";

type Page = "chat" | "contracts" | "library" | "admin";
type Example = { id: string; title: string; description: string };
const suggestions = [
  {
    icon: ShieldCheck,
    tag: "TERCEIRIZAÇÃO",
    title: "Quem responde pelas obrigações trabalhistas?",
    question:
      "Quais responsabilidades trabalhistas a contratante tem na terceirização de serviços?",
  },
  {
    icon: FileText,
    tag: "CONTRATOS",
    title: "O que conferir em um contrato de serviços?",
    question:
      "Quais informações devem constar no contrato de prestação de serviços a terceiros?",
  },
  {
    icon: Clock3,
    tag: "ROTINAS DE RH",
    title: "Como funciona o contrato temporário?",
    question:
      "Em quais situações uma empresa pode contratar trabalho temporário?",
  },
];

function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "small" : ""}`}>
      <span className="brand-icon">
        <Scale size={23} />
      </span>
      <span>
        Juris<span className="brand-light">Assist</span>
        <small>INTELIGÊNCIA JURÍDICA</small>
      </span>
    </div>
  );
}
function Badge({
  children,
  tone = "",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty">
      <FolderOpen size={32} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await post<{ user: User; csrf_token: string }>(
        "/auth/login",
        { email, password },
      );
      setCsrf(result.csrf_token);
      onLogin(result.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <section className="login-story">
        <Brand />
        <div className="story-content">
          <span className="eyebrow light">CLAREZA PARA DECIDIR MELHOR</span>
          <h1>
            O conhecimento jurídico.
            <br />
            <em>Mais perto da sua equipe.</em>
          </h1>
          <p>
            Pesquise a legislação, examine contratos e encontre o fundamento de
            cada resposta.
          </p>
          <div className="story-proof">
            <ShieldCheck />
            <div>
              <strong>Uma fonte para cada afirmação</strong>
              <span>
                Evidências verificáveis. Revisão humana. Controle local.
              </span>
            </div>
          </div>
        </div>
        <span className="story-foot">
          TRABALHISTA &nbsp; / &nbsp; TERCEIRIZAÇÃO &nbsp; / &nbsp; CONTRATOS
        </span>
      </section>
      <main className="login-form">
        <Badge tone="mint">
          <span className="dot" /> AMBIENTE LOCAL
        </Badge>
        <h2>Bem-vindo ao JurisAssist</h2>
        <p>Entre para acessar seu espaço de pesquisa.</p>
        <form onSubmit={submit}>
          <label>
            E-mail
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="seu.email@exemplo.com"
            />
          </label>
          <label>
            Senha
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Sua senha local"
            />
          </label>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button className="button primary full" disabled={busy}>
            {busy ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <>
                Entrar no meu espaço
                <ArrowRight size={18} />
              </>
            )}
          </button>
        </form>
        <div className="setup-note">
          <Settings2 size={18} />
          <div>
            <strong>Primeiro acesso?</strong>
            <p>
              Crie sua conta pelo comando <code>jurisassist create-user</code>.
              As instruções estão no README do projeto.
            </p>
          </div>
        </div>
        <p className="login-foot">
          Portfólio independente · Documentos fictícios e fontes públicas
        </p>
      </main>
    </div>
  );
}

function CitationCard({
  citation,
  index,
}: {
  citation: Citation;
  index: number;
}) {
  return (
    <article className="citation-card">
      <div className="citation-heading">
        <span className="reference-number">{index + 1}</span>
        <strong>{citation.title}</strong>
      </div>
      <div className="citation-locator">{citation.locator}</div>
      <blockquote>{citation.text}</blockquote>
      <div className="citation-meta">
        Versão {citation.version} · Coleta {date(citation.collected_at)}
      </div>
      {citation.url && (
        <a href={citation.url} target="_blank" rel="noreferrer">
          Abrir fonte oficial
          <ExternalLink size={12} />
        </a>
      )}
    </article>
  );
}

function FindingReview({
  finding,
  index,
  saved,
  analysisId,
  onSave,
  onEvidence,
}: {
  finding: Finding;
  index: number;
  saved?: Review;
  analysisId: string;
  onSave: () => void;
  onEvidence: () => void;
}) {
  const [decision, setDecision] = useState(saved?.decision || "pending");
  const [note, setNote] = useState(saved?.note || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(`/analyses/${analysisId}/reviews/${index}`, {
        method: "PUT",
        body: JSON.stringify({ decision, note }),
      });
      onSave();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="finding">
      <div className="row between">
        <h3>{finding.title}</h3>
        <Badge tone={finding.priority === "high" ? "amber" : ""}>
          {
            {
              high: "Alta atenção",
              medium: "Atenção moderada",
              low: "Conferência",
            }[finding.priority]
          }
        </Badge>
      </div>
      <p>{finding.detail}</p>
      <blockquote>“{finding.quote}”</blockquote>
      <button className="text-button" onClick={onEvidence}>
        <BookOpen size={14} />
        Ver cláusula e fundamento
      </button>
      <div className="checklist">
        <CheckCheck size={18} />
        <span>{finding.checklist}</span>
      </div>
      <label>
        Decisão do revisor
        <select value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="pending">Pendente de revisão</option>
          <option value="approved">Concordo com o ponto identificado</option>
          <option value="disagreed">Discordo do ponto identificado</option>
        </select>
      </label>
      <label>
        Nota de revisão
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={2000}
          placeholder="Registre sua avaliação e os próximos passos."
          rows={2}
        />
      </label>
      <button className="button secondary" disabled={busy} onClick={save}>
        {busy ? (
          <LoaderCircle className="spin" size={15} />
        ) : (
          <Check size={15} />
        )}
        Salvar revisão
      </button>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
    </article>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [page, setPage] = useState<Page>("chat");
  const [status, setStatus] = useState<Status | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [analysisList, setAnalysisList] = useState<AnalysisList[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [tracked, setTracked] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<Doc | null>(null);
  const [attested, setAttested] = useState(false);
  const stream = useRef<EventSource | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async (who: User) => {
    const [s, c, d, a, j, e] = await Promise.all([
      api<Status>("/status"),
      api<Conversation[]>("/conversations"),
      api<Doc[]>("/documents"),
      api<AnalysisList[]>("/analyses"),
      api<Job[]>("/jobs"),
      api<Example[]>("/examples"),
    ]);
    setStatus(s);
    setConversations(c);
    setDocs(d);
    setAnalysisList(a);
    setJobs(j);
    setExamples(e);
    if (who.role === "admin") {
      const [ss, o] = await Promise.all([
        api<Source[]>("/admin/sources"),
        api<Overview>("/admin/overview"),
      ]);
      setSources(ss);
      setOverview(o);
    }
  }, []);
  useEffect(() => {
    let alive = true;
    api<User>("/auth/me")
      .then((u) => {
        if (alive) setUser(u);
      })
      .catch(() => {})
      .finally(() => {
        if (alive) setInitializing(false);
      });
    const expired = () => {
      setUser(null);
      setCsrf("");
      stream.current?.close();
    };
    window.addEventListener("session-expired", expired);
    return () => {
      alive = false;
      window.removeEventListener("session-expired", expired);
      stream.current?.close();
    };
  }, []);
  useEffect(() => {
    if (!user) return;
    refresh(user).catch((e) => setError(e.message));
    const timer = window.setInterval(
      () => refresh(user).catch(() => {}),
      15000,
    );
    return () => window.clearInterval(timer);
  }, [user, refresh]);
  useEffect(() => {
    let alive = true;
    if (!active) {
      setMessages([]);
      return;
    }
    api<Message[]>(`/conversations/${active}/messages`)
      .then((m) => {
        if (alive) setMessages(m);
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [active]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, tracked?.stage]);
  useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(""), 5000);
    return () => window.clearTimeout(t);
  }, [notice]);
  useEffect(() => {
    if (!evidenceOpen && !preview) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const selector =
      'button:not([disabled]),a[href],input:not([disabled]),textarea,select,[tabindex="0"]';
    dialog?.querySelector<HTMLElement>(selector)?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setEvidenceOpen(false);
        setPreview(null);
      }
      if (e.key !== "Tab" || !dialog) return;
      const items = [...dialog.querySelectorAll<HTMLElement>(selector)];
      const first = items[0],
        last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, [evidenceOpen, preview]);

  async function loadAnalysis(id: string) {
    try {
      setAnalysis(await api<Analysis>(`/analyses/${id}`));
      setPage("contracts");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function showEvidence(items: Citation[]) {
    setCitations(items);
    setEvidenceOpen(true);
  }
  function watch(job: Job, conversationId?: string) {
    conversationId = conversationId || job.conversation_id;
    if (job.kind === "chat" && conversationId) {
      setActive(conversationId);
      setPage("chat");
      setBusy(true);
    }
    stream.current?.close();
    setTracked(job);
    const events = new EventSource(`/api/v1/jobs/${job.id}/events`, {
      withCredentials: true,
    });
    stream.current = events;
    events.addEventListener("status", (event) =>
      setTracked(JSON.parse((event as MessageEvent).data)),
    );
    events.addEventListener("final", async (event) => {
      events.close();
      const done = JSON.parse((event as MessageEvent).data) as Job;
      setTracked(null);
      setBusy(false);
      try {
        if (conversationId)
          setMessages(
            await api<Message[]>(`/conversations/${conversationId}/messages`),
          );
        if (done.result.analysis_id)
          await loadAnalysis(String(done.result.analysis_id));
        if (user) await refresh(user);
        setNotice("Processamento concluído.");
      } catch (e) {
        setError((e as Error).message);
      }
    });
    events.addEventListener("error", (event) => {
      if ((event as MessageEvent).data) {
        events.close();
        const failed = JSON.parse((event as MessageEvent).data);
        setError(failed.error || failed.detail || "A tarefa falhou.");
        setTracked(null);
        setBusy(false);
        if (user) refresh(user).catch(() => {});
      } else if (events.readyState === EventSource.CLOSED) {
        setTracked(null);
        setBusy(false);
        setError(
          "Conexão de acompanhamento encerrada. A tarefa continua disponível em Administração.",
        );
      }
    });
  }
  async function send(question = input) {
    if (busy || tracked || question.trim().length < 3) return;
    setError("");
    setBusy(true);
    setPage("chat");
    try {
      let id = active;
      if (!id) {
        const c = await post<Conversation>("/conversations", {
          title: "Nova consulta",
        });
        id = c.id;
        setActive(id);
      }
      const job = await post<Job>(`/conversations/${id}/messages`, {
        content: question.trim(),
      });
      setInput("");
      setMessages(await api<Message[]>(`/conversations/${id}/messages`));
      if (user) setConversations(await api<Conversation[]>("/conversations"));
      watch(job, id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  async function useExample(id: string) {
    setError("");
    try {
      const result = await post<{ document: Doc; job: Job }>(`/examples/${id}`);
      watch(result.job);
      if (user) await refresh(user);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function upload(file?: File) {
    if (!file) return;
    setError("");
    const data = new FormData();
    data.append("file", file);
    data.append("synthetic", "true");
    try {
      const result = await api<{ document: Doc; job: Job }>("/documents", {
        method: "POST",
        body: data,
      });
      watch(result.job);
      if (user) await refresh(user);
    } catch (e) {
      setError((e as Error).message);
    }
    if (uploadRef.current) uploadRef.current.value = "";
  }
  async function analyze(id: string) {
    try {
      setError("");
      const job = await post<Job>("/analyses", { document_id: id });
      watch(job);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function previewDoc(id: string) {
    try {
      setAttested(false);
      setPreview(await api<Doc>(`/documents/${id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function approve(doc: Doc) {
    try {
      const job = await post<Job>(`/admin/documents/${doc.id}/approve`);
      setPreview(null);
      watch(job);
      if (user) await refresh(user);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function fetchSource(id: string) {
    try {
      watch(await post<Job>(`/admin/sources/${id}/fetch`));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function feedback(id: string, rating: number) {
    try {
      await post("/feedback", { message_id: id, rating });
      setNotice("Obrigado. Sua avaliação foi registrada.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function logout() {
    try {
      await post("/auth/logout");
      setUser(null);
      setCsrf("");
      setActive(null);
      setMessages([]);
      setCitations([]);
      setAnalysis(null);
      setDocs([]);
      setConversations([]);
      stream.current?.close();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function newChat() {
    if (busy) return;
    setActive(null);
    setPage("chat");
    setMobileMenu(false);
    setCitations([]);
    setEvidenceOpen(false);
    inputRef.current?.focus();
  }
  function exportAnalysis() {
    if (!analysis) return;
    const blob = new Blob([JSON.stringify(analysis, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `jurisassist-analise-${analysis.id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  if (initializing)
    return (
      <div className="loading-page">
        <LoaderCircle className="spin" />
        <p>Preparando seu espaço…</p>
      </div>
    );
  if (!user) return <Login onLogin={setUser} />;
  const titles = {
    chat: ["Assistente jurídico", "Pesquisa fundamentada para o seu dia a dia"],
    contracts: [
      "Análise de contratos",
      "Da leitura à revisão, com cada evidência à mão",
    ],
    library: [
      "Biblioteca jurídica",
      "Fontes oficiais e versões disponíveis para consulta",
    ],
    admin: ["Administração", "Fontes, processamento e qualidade do assistente"],
  };
  const contracts = docs.filter((d) => d.kind === "contract");
  const laws = docs.filter(
    (d) =>
      d.kind === "law" &&
      `${d.title} ${d.status}`.toLowerCase().includes(query.toLowerCase()),
  );
  const activeJobs = jobs.filter((j) =>
    ["queued", "running"].includes(j.status),
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Ir para o conteúdo
      </a>
      {mobileMenu && (
        <button
          className="sidebar-scrim"
          aria-label="Fechar menu"
          onClick={() => setMobileMenu(false)}
        />
      )}
      <aside className={`sidebar ${mobileMenu ? "mobile-open" : ""}`}>
        <Brand />
        <button className="new-chat" onClick={newChat} disabled={busy}>
          <Plus size={18} />
          Nova consulta<span>+</span>
        </button>
        <div className="nav-label">SEU ESPAÇO</div>
        <nav aria-label="Navegação principal">
          {(
            [
              ["chat", MessageSquare, "Assistente jurídico"],
              ["contracts", FileCheck2, "Análise de contratos"],
              ["library", BookOpen, "Biblioteca jurídica"],
              ...(user.role === "admin"
                ? [["admin", Settings2, "Administração"]]
                : []),
            ] as const
          ).map(([id, Icon, label]) => (
            <button
              key={String(id)}
              className={page === id ? "active" : ""}
              onClick={() => {
                setPage(id as Page);
                setMobileMenu(false);
              }}
            >
              <Icon size={18} />
              <span>{String(label)}</span>
              {page === id && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="nav-label history-label">
          CONSULTAS RECENTES<span>{conversations.length}</span>
        </div>
        <div className="history">
          {conversations.length ? (
            conversations.slice(0, 12).map((c) => (
              <button
                key={c.id}
                className={active === c.id ? "selected" : ""}
                disabled={busy}
                onClick={() => {
                  setActive(c.id);
                  setPage("chat");
                  setMobileMenu(false);
                }}
              >
                <MessageSquare size={14} />
                <span>{c.title}</span>
              </button>
            ))
          ) : (
            <p>Suas consultas aparecerão aqui.</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="local-note">
            <span className="dot" />
            <div>
              <strong>Seu ambiente, seus dados</strong>
              <span>Processamento local</span>
            </div>
            <ShieldCheck size={17} />
          </div>
          <div className="user">
            <span className="avatar">
              {user.name
                .split(" ")
                .map((n) => n[0])
                .slice(0, 2)
                .join("")}
            </span>
            <div>
              <strong>{user.name}</strong>
              <span>
                {user.role === "admin" ? "Administrador" : "Pesquisador"}
              </span>
            </div>
            <button className="icon-button" aria-label="Sair" onClick={logout}>
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Abrir menu"
            onClick={() => setMobileMenu(true)}
          >
            <Menu />
          </button>
          <div className="breadcrumb">
            Meu espaço
            <ChevronRight size={13} />
            <strong>{titles[page][0]}</strong>
          </div>
          <div className="topbar-right">
            <Badge tone={status?.model_installed ? "mint" : "amber"}>
              <span className="dot" />
              {status?.model_installed
                ? "IA local conectada"
                : "IA local pendente"}
            </Badge>
            <button
              className="icon-button"
              aria-label="Ajuda sobre o ambiente"
              onClick={() =>
                setNotice(
                  "Prepare o Ollama e aprove as fontes em Administração. Consulte o README para os comandos de instalação.",
                )
              }
            >
              <CircleHelp size={19} />
            </button>
          </div>
        </header>
        <main
          id="main"
          className={`main-content ${page === "chat" ? "chat-main" : ""}`}
        >
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                JURISASSIST /{" "}
                {page === "chat"
                  ? "PESQUISA"
                  : page === "contracts"
                    ? "DOCUMENTOS"
                    : page === "library"
                      ? "CONHECIMENTO"
                      : "OPERAÇÃO"}
              </span>
              <h1>{titles[page][0]}</h1>
              <p>{titles[page][1]}</p>
            </div>
            <Badge>
              <Layers3 size={13} />
              {status?.basis.indexed_sources ?? 0} fontes ativas
            </Badge>
          </div>
          {error && (
            <div className="alert error" role="alert">
              <span>{error}</span>
              <button aria-label="Fechar aviso" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {!tracked && activeJobs.length > 0 && (
            <div className="alert progress" role="status">
              <Clock3 size={17} />
              <span>Você tem {activeJobs.length} tarefa(s) em andamento.</span>
              <button
                className="text-button"
                onClick={() => watch(activeJobs[0])}
              >
                Acompanhar
              </button>
            </div>
          )}
          {tracked && (page !== "chat" || tracked.kind !== "chat") && (
            <div className="alert progress" role="status">
              <LoaderCircle size={17} className="spin" />
              <span>{tracked.stage}</span>
              <Badge>{statusLabel[tracked.status]}</Badge>
            </div>
          )}
          {page === "chat" && (
            <div className="chat-layout">
              <section className="chat-column" aria-label="Consulta jurídica">
                {messages.length === 0 ? (
                  <div className="chat-welcome">
                    <div className="welcome-emblem">
                      <Scale size={31} />
                      <span>
                        <Sparkles size={13} />
                      </span>
                    </div>
                    <Badge tone="mint">CONHECIMENTO COM FUNDAMENTO</Badge>
                    <h2>Qual é a sua dúvida jurídica?</h2>
                    <p>
                      Um ponto de partida claro para questões trabalhistas e
                      contratuais.
                      <br />
                      Pergunte, explore as fontes e leve os fundamentos para sua
                      decisão.
                    </p>
                    <div className="suggestions">
                      {suggestions.map((s) => (
                        <button
                          key={s.tag}
                          onClick={() => send(s.question)}
                          disabled={busy || !!tracked}
                        >
                          <s.icon size={21} />
                          <span className="suggestion-tag">{s.tag}</span>
                          <strong>{s.title}</strong>
                          <ArrowRight size={17} />
                        </button>
                      ))}
                    </div>
                    <div className="welcome-tip">
                      <BookOpen size={16} />
                      <span>
                        As respostas mostram os trechos e a versão das fontes
                        consultadas.
                      </span>
                    </div>
                    {status && !status.basis.indexed_sources && (
                      <div className="setup-banner">
                        <span className="setup-step">1</span>
                        <div>
                          <strong>
                            Vamos preparar sua base de conhecimento
                          </strong>
                          <p>
                            As fontes oficiais precisam ser coletadas, revisadas
                            e indexadas.
                          </p>
                        </div>
                        {user.role === "admin" && (
                          <button
                            className="text-button"
                            onClick={() => setPage("admin")}
                          >
                            Preparar fontes
                            <ArrowRight size={15} />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="message-list" aria-live="polite">
                    {messages.map((m) => (
                      <article className={`message ${m.role}`} key={m.id}>
                        <span className={`message-avatar ${m.role}`}>
                          {m.role === "user" ? (
                            user.name[0]
                          ) : (
                            <Scale size={18} />
                          )}
                        </span>
                        <div className="message-body">
                          <div className="message-author">
                            {m.role === "user" ? "Você" : "JurisAssist"}
                            <span>
                              {new Date(m.created_at + "Z").toLocaleTimeString(
                                "pt-BR",
                                { hour: "2-digit", minute: "2-digit" },
                              )}
                            </span>
                            {m.role !== "user" && (
                              <Badge tone="mint">
                                {m.evidence?.status === "answered"
                                  ? "Com evidências"
                                  : m.evidence?.status === "clarification"
                                    ? "Esclarecimento"
                                    : "Limite da base"}
                              </Badge>
                            )}
                          </div>
                          <p>{m.content}</p>
                          {m.evidence?.claims?.map((c, i) => (
                            <p key={i} className="claim">
                              {c.text}
                              <button
                                className="inline-reference"
                                onClick={() =>
                                  showEvidence(
                                    m.evidence.citations.filter((x) =>
                                      c.citation_ids.includes(x.id),
                                    ),
                                  )
                                }
                                aria-label={`Ver fundamentos da afirmação ${i + 1}`}
                              >
                                <BookOpen size={12} />
                                {c.citation_ids.length}
                              </button>
                            </p>
                          ))}
                          {m.evidence?.questions?.map((q, i) => (
                            <p className="clarification" key={i}>
                              {q}
                            </p>
                          ))}
                          {m.evidence?.basis?.warning && (
                            <p className="source-warning">
                              <Clock3 size={13} />
                              {m.evidence.basis.warning}
                            </p>
                          )}
                          {m.role !== "user" && (
                            <div className="message-actions">
                              <button
                                onClick={() =>
                                  showEvidence(m.evidence.citations || [])
                                }
                              >
                                <BookOpen size={14} />
                                {m.evidence.citations?.length || 0} fontes
                                consultadas
                              </button>
                              <span />
                              <button
                                aria-label="Resposta útil"
                                onClick={() => feedback(m.id, 1)}
                              >
                                <ThumbsUp size={14} />
                              </button>
                              <button
                                aria-label="Resposta precisa melhorar"
                                onClick={() => feedback(m.id, -1)}
                              >
                                <ThumbsDown size={14} />
                              </button>
                            </div>
                          )}
                        </div>
                      </article>
                    ))}
                    {busy && (
                      <div className="thinking" role="status">
                        <LoaderCircle className="spin" size={18} />
                        {tracked?.stage || "Preparando consulta…"}
                      </div>
                    )}
                    <div ref={bottom} />
                  </div>
                )}
                <form
                  className="composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    send();
                  }}
                >
                  <label className="sr-only" htmlFor="question">
                    Sua dúvida jurídica
                  </label>
                  <textarea
                    ref={inputRef}
                    id="question"
                    placeholder="Descreva sua dúvida. Inclua o contexto para uma resposta mais útil…"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    maxLength={4000}
                    rows={2}
                    disabled={busy || !!tracked}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        send();
                      }
                    }}
                  />
                  <div className="composer-footer">
                    <span>
                      <ShieldCheck size={13} />
                      Use apenas situações e dados fictícios
                    </span>
                    <button
                      className="send-button"
                      aria-label="Enviar consulta"
                      disabled={busy || !!tracked || input.trim().length < 3}
                    >
                      {busy ? (
                        <LoaderCircle size={17} className="spin" />
                      ) : (
                        <Send size={17} />
                      )}
                    </button>
                  </div>
                </form>
                <p className="chat-disclaimer">
                  Apoio à pesquisa e revisão humana. Confira as fontes e sua
                  aplicabilidade ao caso.
                </p>
              </section>
              <aside className="context-panel">
                <div className="context-title">
                  <BookOpen size={17} />
                  <strong>Sua pesquisa, com contexto</strong>
                </div>
                <div className="context-illustration">
                  <div className="document-drawing">
                    <Scale size={23} />
                    <i />
                    <i />
                    <i />
                    <span>
                      <Check size={17} />
                    </span>
                  </div>
                </div>
                <h3>O fundamento faz a diferença.</h3>
                <p>
                  Cada referência permite conferir de onde veio a informação e
                  qual texto foi consultado.
                </p>
                <div className="context-divider" />
                <span className="eyebrow">BASE DE CONHECIMENTO</span>
                {[
                  {
                    id: "clt",
                    name: "Legislação trabalhista",
                    sub: "Consolidação das Leis do Trabalho",
                  },
                  {
                    id: "terceirizacao",
                    name: "Trabalho e terceirização",
                    sub: "Lei nº 6.019/1974",
                  },
                  {
                    id: "codigo-civil",
                    name: "Contratos e serviços",
                    sub: "Código Civil",
                  },
                ].map((s) => (
                  <div className="source-mini" key={s.id}>
                    <span className="source-mini-icon">
                      <FileText size={17} />
                    </span>
                    <div>
                      <strong>{s.name}</strong>
                      <span>{s.sub}</span>
                    </div>
                    <span
                      className={`source-state ${docs.some((d) => d.source_id === s.id && d.status === "indexed") ? "ready" : ""}`}
                    />
                  </div>
                ))}
                <button
                  className="library-link"
                  onClick={() => setPage("library")}
                >
                  Explorar biblioteca
                  <ArrowRight size={14} />
                </button>
                <div className="context-foot">
                  <ShieldCheck size={19} />
                  <div>
                    <strong>IA com responsabilidade</strong>
                    <span>
                      Fontes rastreáveis e espaço para o julgamento
                      profissional.
                    </span>
                  </div>
                </div>
              </aside>
            </div>
          )}
          {page === "contracts" && (
            <div className="content-stack">
              {!analysis ? (
                <>
                  <div className="section-intro">
                    <div>
                      <h2>Um olhar atento ao seu contrato</h2>
                      <p>
                        Identifique obrigações, prazos e pontos que merecem
                        revisão.
                      </p>
                    </div>
                    <label
                      className="button primary upload-label"
                      role="button"
                      tabIndex={tracked ? -1 : 0}
                      aria-disabled={!!tracked}
                      onKeyDown={(event) => {
                        if (
                          !tracked &&
                          (event.key === "Enter" || event.key === " ")
                        ) {
                          event.preventDefault();
                          uploadRef.current?.click();
                        }
                      }}
                    >
                      <Upload size={16} />
                      Enviar contrato fictício
                      <input
                        ref={uploadRef}
                        type="file"
                        disabled={!!tracked}
                        accept=".pdf,.txt,.md"
                        onChange={(e) => upload(e.target.files?.[0])}
                      />
                    </label>
                  </div>
                  <p className="muted small-text">
                    PDF textual, TXT ou Markdown · Até 10 MB e 50 páginas ·
                    Somente documentos fictícios
                  </p>
                  <div className="example-grid">
                    {examples.map((e) => (
                      <article className="example-card" key={e.id}>
                        <span className="tile-icon">
                          <FileText size={22} />
                        </span>
                        <Badge>EXEMPLO FICTÍCIO</Badge>
                        <h3>{e.title}</h3>
                        <p>{e.description}</p>
                        <button
                          className="text-button"
                          onClick={() => useExample(e.id)}
                          disabled={!!tracked}
                        >
                          Usar este exemplo
                          <ArrowRight size={15} />
                        </button>
                      </article>
                    ))}
                  </div>
                  <section className="panel">
                    <div className="panel-heading">
                      <h2>Meus contratos</h2>
                      <Badge>{contracts.length} documentos</Badge>
                    </div>
                    {contracts.length ? (
                      <div className="document-list">
                        {contracts.map((d) => (
                          <div className="document-row" key={d.id}>
                            <FileText size={22} />
                            <div>
                              <strong>{d.title}</strong>
                              <span>Adicionado em {date(d.created_at)}</span>
                            </div>
                            <Badge
                              tone={d.status === "ready" ? "mint" : "amber"}
                            >
                              {statusLabel[d.status]}
                            </Badge>
                            <button
                              className="text-button"
                              onClick={() => previewDoc(d.id)}
                            >
                              Ver texto
                            </button>
                            <button
                              className="button secondary"
                              disabled={d.status !== "ready" || !!tracked}
                              onClick={() => analyze(d.id)}
                            >
                              Analisar
                              <ArrowRight size={14} />
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <Empty
                        title="Seus contratos aparecerão aqui"
                        text="Comece com um dos exemplos ou envie um documento fictício."
                      />
                    )}
                  </section>
                  <section className="panel">
                    <div className="panel-heading">
                      <h2>Análises realizadas</h2>
                    </div>
                    {analysisList.length ? (
                      analysisList.map((a) => (
                        <button
                          className="analysis-row"
                          key={a.id}
                          onClick={() => loadAnalysis(a.id)}
                        >
                          <FileCheck2 size={21} />
                          <div>
                            <strong>{a.title}</strong>
                            <span>{date(a.created_at)}</span>
                          </div>
                          <ChevronRight size={18} />
                        </button>
                      ))
                    ) : (
                      <Empty
                        title="Uma nova perspectiva sobre cada cláusula"
                        text="Após o processamento, a análise ficará disponível para revisão."
                      />
                    )}
                  </section>
                </>
              ) : (
                <>
                  <div className="row between">
                    <button
                      className="text-button"
                      onClick={() => setAnalysis(null)}
                    >
                      ← Voltar aos contratos
                    </button>
                    <button
                      className="button secondary"
                      onClick={exportAnalysis}
                    >
                      <ArrowDownToLine size={15} />
                      Exportar análise e revisões
                    </button>
                  </div>
                  <section className="panel analysis-summary">
                    <Badge tone="mint">
                      <FileCheck2 size={14} />
                      ANÁLISE FUNDAMENTADA
                    </Badge>
                    <h2>Resumo do contrato</h2>
                    <p>{analysis.result.summary}</p>
                    <div className="row">
                      <Badge>
                        {analysis.result.coverage?.processed_chunks}/
                        {analysis.result.coverage?.total_chunks} trechos
                        processados
                      </Badge>
                      <Badge>{analysis.result.model}</Badge>
                    </div>
                    {analysis.result.basis?.warning && (
                      <p className="source-warning">
                        {analysis.result.basis.warning}
                      </p>
                    )}
                  </section>
                  <div className="two-columns">
                    {(["obligations", "deadlines"] as const).map((key) => (
                      <section className="panel" key={key}>
                        <h2>
                          {key === "obligations"
                            ? "Obrigações identificadas"
                            : "Prazos identificados"}
                        </h2>
                        {analysis.result[key]?.length ? (
                          analysis.result[key]?.map((c, i) => (
                            <p key={i} className="claim">
                              {c.text}
                              <button
                                className="inline-reference"
                                onClick={() =>
                                  showEvidence(
                                    analysis.result.citations.filter((x) =>
                                      c.citation_ids.includes(x.id),
                                    ),
                                  )
                                }
                              >
                                <BookOpen size={12} />
                              </button>
                            </p>
                          ))
                        ) : (
                          <p className="muted">
                            Nenhum item identificado com suporte suficiente.
                          </p>
                        )}
                      </section>
                    ))}
                  </div>
                  <div className="section-intro">
                    <h2>Pontos para revisão humana</h2>
                    <Badge>
                      {
                        analysis.reviews.filter((r) => r.decision !== "pending")
                          .length
                      }
                      /{analysis.result.findings?.length || 0} revisados
                    </Badge>
                  </div>
                  {analysis.result.findings?.length ? (
                    analysis.result.findings.map((f, i) => (
                      <FindingReview
                        key={`${analysis.id}-${i}`}
                        finding={f}
                        index={i}
                        analysisId={analysis.id}
                        saved={analysis.reviews.find((r) => r.item_index === i)}
                        onSave={() => {
                          loadAnalysis(analysis.id);
                          setNotice("Revisão salva.");
                        }}
                        onEvidence={() =>
                          showEvidence(
                            analysis.result.citations.filter(
                              (c) =>
                                c.id === f.contract_chunk_id ||
                                f.citation_ids.includes(c.id),
                            ),
                          )
                        }
                      />
                    ))
                  ) : (
                    <Empty
                      title="Nenhum ponto identificado"
                      text="A ausência de apontamentos não equivale à aprovação jurídica do contrato."
                    />
                  )}
                </>
              )}
            </div>
          )}
          {page === "library" && (
            <div className="content-stack">
              <div className="library-banner">
                <span className="tile-icon">
                  <BookOpen size={24} />
                </span>
                <div>
                  <h2>Conhecimento que você pode conferir</h2>
                  <p>
                    Versões preservadas para manter a rastreabilidade de cada
                    resposta.
                  </p>
                </div>
                <Badge tone="mint">FONTES OFICIAIS</Badge>
              </div>
              <label className="search-box">
                <Search size={18} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Pesquisar por fonte ou situação…"
                  aria-label="Pesquisar biblioteca"
                />
              </label>
              {laws.length ? (
                <div className="law-grid">
                  {laws.map((d) => (
                    <article className="law-card" key={d.id}>
                      <div className="row between">
                        <FileText size={26} />
                        <Badge tone={d.status === "indexed" ? "mint" : "amber"}>
                          {statusLabel[d.status]}
                        </Badge>
                      </div>
                      <h2>{d.title}</h2>
                      <p>Versão {d.version}</p>
                      <div className="law-date">
                        <Clock3 size={14} />
                        Coletada em {date(d.created_at)}
                      </div>
                      <div className="row between">
                        <button
                          className="text-button"
                          onClick={() => previewDoc(d.id)}
                        >
                          Consultar texto
                          <ArrowRight size={14} />
                        </button>
                        {d.url && (
                          <a
                            className="icon-button"
                            aria-label="Abrir fonte oficial"
                            target="_blank"
                            rel="noreferrer"
                            href={d.url}
                          >
                            <ExternalLink size={17} />
                          </a>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <Empty
                  title="Nenhuma fonte encontrada"
                  text="O administrador pode coletar as fontes oficiais na área de Administração."
                />
              )}
            </div>
          )}
          {page === "admin" && user.role === "admin" && (
            <div className="content-stack">
              <div className="stats-grid">
                <div>
                  <span>Fontes aprovadas</span>
                  <strong>
                    {status?.basis.indexed_sources || 0}
                    <small>/ 3</small>
                  </strong>
                  <p>Disponíveis para recuperação</p>
                </div>
                <div>
                  <span>Tarefas em andamento</span>
                  <strong>{activeJobs.length}</strong>
                  <p>Fila persistente de processamento</p>
                </div>
                <div>
                  <span>Avaliações registradas</span>
                  <strong>{overview?.evaluations.length || 0}</strong>
                  <p>Experimentos executados localmente</p>
                </div>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Fontes oficiais</h2>
                    <p>Coletar → conferir o texto → aprovar → indexar</p>
                  </div>
                  <Badge tone={status?.basis.pending_update ? "amber" : "mint"}>
                    {status?.basis.pending_update
                      ? "Revisão pendente"
                      : "Controle de versões ativo"}
                  </Badge>
                </div>
                {sources.map((s) => (
                  <div className="document-row" key={s.id}>
                    <BookOpen size={22} />
                    <div>
                      <strong>{s.title}</strong>
                      <span>
                        Última verificação: {date(s.checked_at)}
                        {s.check_error ? ` · Falha: ${s.check_error}` : ""}
                      </span>
                    </div>
                    <button
                      className="button secondary"
                      disabled={!!tracked}
                      onClick={() => fetchSource(s.id)}
                    >
                      Verificar fonte
                      <ArrowRight size={14} />
                    </button>
                  </div>
                ))}
                <div className="pending-versions">
                  {docs
                    .filter(
                      (d) =>
                        d.kind === "law" &&
                        ["pending_review", "indexing"].includes(d.status),
                    )
                    .map((d) => (
                      <div key={d.id} className="pending-row">
                        <div>
                          <strong>{d.title}</strong>
                          <span>
                            {statusLabel[d.status]} · {d.version}
                          </span>
                        </div>
                        {d.status === "pending_review" ? (
                          <button
                            className="text-button"
                            onClick={() => previewDoc(d.id)}
                          >
                            Revisar versão
                            <ChevronRight size={15} />
                          </button>
                        ) : (
                          <button
                            className="text-button"
                            disabled={!!tracked}
                            onClick={async () => {
                              try {
                                watch(
                                  await post<Job>(
                                    `/admin/documents/${d.id}/reindex`,
                                  ),
                                );
                              } catch (e) {
                                setError((e as Error).message);
                              }
                            }}
                          >
                            Reenfileirar indexação
                          </button>
                        )}
                      </div>
                    ))}
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Processamento recente</h2>
                  <button className="text-button" onClick={() => refresh(user)}>
                    Atualizar
                  </button>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Tarefa</th>
                        <th>Situação</th>
                        <th>Etapa</th>
                        <th>Tentativas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview?.jobs.map((j) => (
                        <tr key={j.id}>
                          <td>
                            <strong>
                              {
                                {
                                  chat: "Consulta jurídica",
                                  index: "Indexação",
                                  fetch: "Coleta oficial",
                                  analyze: "Análise contratual",
                                }[j.kind]
                              }
                            </strong>
                            <small>{j.id.slice(0, 8)}</small>
                          </td>
                          <td>
                            <Badge
                              tone={
                                j.status === "failed"
                                  ? "amber"
                                  : j.status === "completed"
                                    ? "mint"
                                    : ""
                              }
                            >
                              {statusLabel[j.status]}
                            </Badge>
                          </td>
                          <td>
                            {j.error || j.stage}
                            {["queued", "running"].includes(j.status) && (
                              <button
                                className="text-button"
                                onClick={() => watch(j)}
                              >
                                Acompanhar
                              </button>
                            )}
                          </td>
                          <td>{j.attempts}/3</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!overview?.jobs.length && (
                    <Empty
                      title="Nenhuma tarefa executada"
                      text="Comece pela coleta das fontes oficiais."
                    />
                  )}
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Avaliação e experimentos</h2>
                    <p>Busca textual, vetorial e híbrida · Prompts v1 e v2</p>
                  </div>
                </div>
                {overview?.evaluations.length ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Experimento</th>
                          <th>Recall@5</th>
                          <th>Casos</th>
                          <th>Data</th>
                        </tr>
                      </thead>
                      <tbody>
                        {overview.evaluations.map((e) => (
                          <tr key={e.id}>
                            <td>
                              {e.mode} · {e.prompt_version}
                            </td>
                            <td>
                              {e.recall_at_5 == null
                                ? "Não medido"
                                : `${Math.round(e.recall_at_5 * 100)}%`}
                            </td>
                            <td>{e.evaluated}</td>
                            <td>{date(e.created_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="evaluation-empty">
                    <Layers3 size={25} />
                    <h3>Qualidade medida, evolução documentada</h3>
                    <p>
                      Execute <code>jurisassist evaluate --matrix</code> para
                      comparar as estratégias. Os resultados aparecerão aqui.
                    </p>
                  </div>
                )}
              </section>
              <section className="panel">
                <h2>Feedback das respostas</h2>
                {overview?.feedback.length ? (
                  overview.feedback.map((f, i) => (
                    <div className="feedback-row" key={i}>
                      {f.rating > 0 ? (
                        <ThumbsUp size={16} />
                      ) : (
                        <ThumbsDown size={16} />
                      )}
                      <p>
                        {f.comment ||
                          (f.rating > 0
                            ? "Resposta considerada útil"
                            : "Resposta precisa melhorar")}
                      </p>
                      <small>{f.message_id.slice(0, 8)}</small>
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    As avaliações dos usuários aparecerão aqui.
                  </p>
                )}
              </section>
            </div>
          )}
        </main>
        <footer className="workspace-footer">
          <span>
            <Scale size={12} />
            JurisAssist · Pesquisa com evidências
          </span>
          <span>Portfólio independente · Execução local</span>
        </footer>
      </div>
      {notice && (
        <div className="toast" role="status">
          <Check size={17} />
          {notice}
          <button aria-label="Fechar notificação" onClick={() => setNotice("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {evidenceOpen && (
        <div className="drawer-overlay" onClick={() => setEvidenceOpen(false)}>
          <aside
            className="evidence-drawer"
            aria-label="Fontes e evidências"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-heading">
              <div>
                <span className="eyebrow">TRANSPARÊNCIA</span>
                <h2>Fontes e evidências</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Fechar fontes"
                onClick={() => setEvidenceOpen(false)}
              >
                <X />
              </button>
            </div>
            <p className="muted">
              Confira o trecho consultado, sua origem e a versão usada na
              resposta.
            </p>
            {citations.length ? (
              citations.map((c, i) => (
                <CitationCard key={c.id} citation={c} index={i} />
              ))
            ) : (
              <Empty
                title="Sem referências nesta resposta"
                text="O assistente indicou uma limitação da base ou pediu esclarecimentos."
              />
            )}
          </aside>
        </div>
      )}
      {preview && (
        <div className="modal-overlay" onClick={() => setPreview(null)}>
          <section
            className="document-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Texto do documento"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-heading">
              <div>
                <Badge>{statusLabel[preview.status]}</Badge>
                <h2>{preview.title}</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Fechar documento"
                onClick={() => setPreview(null)}
              >
                <X />
              </button>
            </div>
            <div className="document-body">{preview.body}</div>
            {preview.status === "pending_review" && user.role === "admin" && (
              <div className="approval-footer">
                <p>{preview.review_note}</p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={attested}
                    onChange={(e) => setAttested(e.target.checked)}
                  />
                  Conferi a redação, as notas de alteração e a aplicabilidade
                  temporal desta versão.
                </label>
                <button
                  className="button primary"
                  disabled={!attested}
                  onClick={() => approve(preview)}
                >
                  <CheckCheck size={17} />
                  Aprovar versão e indexar
                </button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
