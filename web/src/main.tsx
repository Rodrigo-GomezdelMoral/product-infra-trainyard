import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-600.css";
import "./styles.css";
import { ArrowUp, Check, CircleUserRound, Copy, FileText, LoaderCircle, LogOut, Menu, MessageSquare, Search, SquarePen, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, DEMO, events, OWNER, replay, RUNS, type Ask, type Call, type Conversation, type Run, type Status, type User } from "./api";
import { Approval, Promotion } from "./Cards";

const BRAND = `${import.meta.env.BASE_URL}brand/`;
const POLL = DEMO ? 3000 : 60000;
const GONE = "The canary is no longer waiting for a decision: ask Trainyard for the model status.";
const SUGGESTIONS = ["Which trains should we inspect this week?", "Why is EMU 2417 at risk?", "Is the model drifting?", "Retrain and compare with the current model"];
type Entry =
  | { kind: "user"; text: string }
  | { kind: "answer"; text: string }
  | { kind: "approval"; calls: Call[]; decided?: boolean }
  | { kind: "promotion"; status: Status }
  | { kind: "error"; text: string };

function Actions({ text, about }: { text: string; about?: string }) {
  const [vote, setVote] = useState<boolean>();
  const [copied, setCopied] = useState(false);
  const rate = (helpful: boolean) => (setVote(helpful), about && api.feedback(about, helpful).catch(() => undefined));
  return (
    <div className="actions">
      <button className="icon" aria-label={copied ? "Copied" : "Copy"} onClick={() => navigator.clipboard.writeText(text).then(() => setCopied(true))}>
        {copied ? <Check size={16} /> : <Copy size={16} />}
      </button>
      <button className="icon" aria-label="Helpful" aria-pressed={vote === true} onClick={() => rate(true)}>
        <ThumbsUp size={16} />
      </button>
      <button className="icon" aria-label="Not helpful" aria-pressed={vote === false} onClick={() => rate(false)}>
        <ThumbsDown size={16} />
      </button>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User>({ name: DEMO ? "Visitor" : "", roles: [] });
  const [entries, setEntries] = useState<Entry[]>([]);
  const [conversation, setConversation] = useState<string>();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<string>();
  const [menu, setMenu] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const generation = useRef(0);
  const owner = user.roles.includes(OWNER);
  const live = entries.findLastIndex((entry) => entry.kind === "promotion");
  const latest = entries[live];
  const canary = latest?.kind === "promotion" && latest.status.card?.step === "canary";
  const fail = (failure: unknown) => setEntries((list) => [...list, { kind: "error", text: (failure as Error).message }]);
  const refresh = () => void (!DEMO && user.roles.length && api.conversations().then(setConversations, fail));

  useEffect(() => {
    if (!DEMO) api.me().then((me) => (setUser(me), me.roles.length || fail(new Error("Your account has no Trainyard role."))), fail);
  }, []);
  useEffect(refresh, [user]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
    if (document.activeElement === document.body) thread.current?.focus({ preventScroll: true });
  }, [entries.length]);
  useEffect(() => {
    if (!canary) return;
    const mine = generation.current;
    const update = (status: Status) =>
      mine === generation.current && setEntries((list) => list.map((entry, at) => (at === live ? { kind: "promotion", status: status.card ? status : { outcome: GONE, card: null } } : entry)));
    const timer = setInterval(() => api.promotion().then(update, () => undefined), POLL);
    return () => clearInterval(timer);
  }, [canary, live]);

  async function guard(text: string | undefined, work: (put: (entry?: Entry) => boolean) => Promise<unknown>) {
    const mine = generation.current;
    const put = (entry?: Entry) => mine === generation.current && (!entry || (setEntries((list) => [...list, entry]), true));
    setBusy(true);
    if (text) put({ kind: "user", text });
    await work(put).catch((failure) => put({ kind: "error", text: (failure as Error).message }));
    if (put()) setBusy(false);
  }
  const converse = (text: string | undefined, ask: Ask) =>
    guard(text, async (put) => {
      const calls: Call[] = [];
      let shown: Entry | undefined;
      for await (const { event, data } of events(await api.chat(ask))) {
        if (!put()) break;
        if (event === "conversation") setConversation(data);
        if (event === "approval") calls.push(data);
        if (event === "error") put({ kind: "error", text: data.detail });
        if (event === "text") {
          const before = shown;
          const next: Entry = { kind: "answer", text: (before?.kind === "answer" ? before.text : "") + data };
          if (before) setEntries((list) => list.map((entry) => (entry === before ? next : entry)));
          else put(next);
          shown = next;
        }
        if (event === "done" && calls.length) put({ kind: "approval", calls });
        if (event === "done" && data.card) put({ kind: "promotion", status: { card: data.card } });
      }
      refresh();
    });
  const answer = (index: number, calls: Call[], approve: boolean) => {
    setEntries((list) => list.map((entry, at) => (at === index ? { kind: "approval", calls, decided: approve } : entry)));
    converse(undefined, { conversation, approvals: Object.fromEntries(calls.map((call) => [call.id, approve])) });
  };
  const decide = (word: string) => guard(undefined, async (put) => put({ kind: "promotion", status: await api.decide(word) }));

  function reset(key = "") {
    generation.current += 1;
    setBusy(false);
    setEntries([]);
    setActive(key);
    setMenu(false);
    setConversation(undefined);
  }
  function play(run: Run) {
    reset(run.title);
    replay(run);
    setUser(run.user);
    converse(run.prompt, { message: run.prompt });
  }
  function open(item: Conversation) {
    reset(item.id);
    setConversation(item.id);
    api.turns(item.id).then((turns) => setEntries(turns.map((turn): Entry => (turn.role === "user" ? { kind: "user", ...turn } : { kind: "answer", ...turn }))), fail);
  }
  function forget(item: Conversation) {
    api.forget(item.id).then(() => (setConversations((list) => list.filter((other) => other.id !== item.id)), item.id === active && reset()), fail);
  }
  function suggest(text: string) {
    const run = RUNS.find((item) => item.prompt === text);
    if (!DEMO) converse(text, { message: text, conversation });
    else if (run) play(run);
  }
  function send() {
    if (!draft.trim() || busy || DEMO) return;
    converse(draft.trim(), { message: draft.trim(), conversation });
    setDraft("");
  }

  const heading = DEMO ? "Recorded runs" : "Conversations";
  const Icon = DEMO ? FileText : MessageSquare;
  const items = DEMO
    ? RUNS.map((run) => ({ key: run.title, label: run.title, go: () => play(run), drop: undefined }))
    : conversations.map((item) => ({ key: item.id, label: item.title || "Untitled conversation", go: () => open(item), drop: () => forget(item) }));

  return (
    <div className="app">
      {DEMO && <header className="band">Demo mode · recorded runs from the deployed system</header>}
      <div className="layout">
        <button className="icon menu" aria-label="Sidebar" aria-expanded={menu} onClick={() => setMenu(!menu)}>
          <Menu size={20} />
        </button>
        <aside className={menu ? "sidebar open" : "sidebar"} aria-label="Sidebar">
          <h1>
            <img src={`${BRAND}trainyard-logo.svg`} alt="Trainyard" height={28} />
          </h1>
          <div className="row">
            <button className="primary" onClick={() => reset()}>
              <SquarePen size={16} aria-hidden /> New chat
            </button>
            <button className="icon round" aria-label="Search" aria-expanded={filter !== undefined} onClick={() => setFilter(filter === undefined ? "" : undefined)}>
              <Search size={16} />
            </button>
          </div>
          {filter !== undefined && <input className="search" aria-label="Search the list" autoFocus value={filter} onChange={(event) => setFilter(event.target.value)} />}
          <nav aria-label={heading}>
            <h2>{heading}</h2>
            <ul>
              {items
                .filter((item) => item.label.toLowerCase().includes((filter ?? "").toLowerCase()))
                .map(({ key, label, go, drop }) => (
                  <li key={key}>
                    <button className={key === active ? "item selected" : "item"} aria-current={key === active} onClick={go}>
                      <Icon size={16} aria-hidden /> <span>{label}</span>
                    </button>
                    {drop && (
                      <button className="icon" aria-label={`Delete ${label}`} onClick={drop}>
                        <Trash2 size={16} />
                      </button>
                    )}
                  </li>
                ))}
            </ul>
            {items.length === 0 && <p className="status">{DEMO ? "No recorded runs yet." : "No conversations yet."}</p>}
          </nav>
          <div className="me">
            <CircleUserRound className="avatar" size={28} strokeWidth={1.5} aria-hidden />
            <span>
              {user.name || "Signed out"}
              <small>{owner ? "Model owner" : user.roles.length ? "Maintenance planner" : DEMO ? "Demo" : "No Trainyard role"}</small>
            </span>
            {!DEMO && (
              <a className="icon" href="/.auth/logout" aria-label="Sign out">
                <LogOut size={16} />
              </a>
            )}
          </div>
        </aside>
        <main>
          {entries.length === 0 ? (
            <div className="empty">
              <img src={`${BRAND}trainyard-icon.svg`} alt="" width={56} height={56} />
              <h2>An AI assistant for this week's train inspections, on a model you can trace, compare and roll back.</h2>
              <div className="suggestions">
                {SUGGESTIONS.map((text) => (
                  <button key={text} className="suggestion" disabled={busy || (DEMO && !RUNS.some((run) => run.prompt === text))} onClick={() => suggest(text)}>
                    {text}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="thread" role="log" aria-label="Conversation" aria-busy={busy} key={generation.current} ref={thread} tabIndex={-1}>
              {entries.map((entry, index) =>
                entry.kind === "user" ? (
                  <div className="turn user" key={index}>
                    <CircleUserRound className="avatar" size={28} strokeWidth={1.5} aria-hidden />
                    <p>{entry.text}</p>
                  </div>
                ) : (
                  <section className="turn product" key={index} aria-label="Trainyard">
                    <p className="name">Trainyard</p>
                    {entry.kind === "error" && <p className="status error" role="alert">{entry.text}</p>}
                    {entry.kind === "answer" && (
                      <>
                        <div className="answer">
                          <Markdown remarkPlugins={[remarkGfm]} disallowedElements={["img", "a"]} unwrapDisallowed>
                            {entry.text}
                          </Markdown>
                        </div>
                        <Actions text={entry.text} about={conversation} />
                      </>
                    )}
                    {entry.kind === "approval" && <Approval calls={entry.calls} decided={entry.decided} act={busy ? undefined : (approve) => answer(index, entry.calls, approve)} />}
                    {entry.kind === "promotion" && <Promotion status={entry.status} live={index === live} act={busy ? undefined : decide} />}
                  </section>
                ),
              )}
              {busy && (
                <p className="status">
                  <LoaderCircle size={16} className="spin" aria-hidden /> Working
                </p>
              )}
              <div ref={end} />
            </div>
          )}
          <form className="composer" onSubmit={(event) => (event.preventDefault(), send())}>
            <textarea
              aria-label="Message"
              rows={1}
              value={draft}
              disabled={DEMO}
              placeholder={DEMO ? "Free text needs the deployed system: pick a recorded run" : "Ask the AI assistant about the fleet or the model"}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && (event.preventDefault(), send())}
            />
            <button type="submit" className="send" aria-label="Send" disabled={DEMO || busy || !draft.trim()}>
              <ArrowUp size={18} />
            </button>
          </form>
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
