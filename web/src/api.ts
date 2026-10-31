export type User = { name: string; roles: string[] };
export type Turn = { role: string; text: string };
export type Conversation = { id: string; title: string };
export type Health = { requests: number; failed: number; p95_ms: number; minutes: number; agreement: number | null };
export type Plan = { challenger: string; slot: string; champion: string; live: string };
export type Card = { step: "first" | "shadow" | "canary" | "window"; plan: Plan; facts: Record<string, any> };
export type Status = { outcome?: string | null; card: Card | null };
export type Call = { id: string; tool: string; arguments: Record<string, unknown> };
export type Ask = { message?: string; conversation?: string; approvals?: Record<string, boolean> };
export type Exchange = { method: string; path: string; status: number; ms: number; request?: unknown; json?: unknown; text?: string; type?: string };
export type Run = { title: string; prompt: string; user: User; recorded: string; exchanges: Exchange[] };

export const DEMO = import.meta.env.VITE_DEMO_MODE === "true";
const recordings = DEMO ? Object.values(import.meta.glob<Run | Run[]>("./demo/runs/*.json", { eager: true, import: "default" })) : [];
export const RUNS = recordings.flat();
export const OWNER = "ModelApprover";

let replaying: Exchange[] = [];
const used = new Set<Exchange>();

export function replay(run: Run) {
  replaying = run.exchanges;
  used.clear();
}

function recorded(method: string, path: string, body: unknown): Exchange | undefined {
  const same = replaying.filter((item) => item.method === method && item.path === path && (!item.request || JSON.stringify(item.request) === body));
  return same.find((item) => !used.has(item)) ?? same.at(-1);
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  if (!DEMO) return fetch(path, init);
  const item = recorded(init.method ?? "GET", path, init.body);
  if (!item) return Response.json({ detail: "This step is not part of the recording." }, { status: 404 });
  used.add(item);
  await new Promise((done) => setTimeout(done, item.ms));
  const body = item.json === undefined ? (item.text ?? null) : JSON.stringify(item.json);
  return new Response(body, { status: item.status, headers: { "content-type": item.type ?? "application/json" } });
}

async function checked(path: string, init?: RequestInit): Promise<Response> {
  const response = await call(path, init);
  if (response.ok) return response;
  const body = await response.json().catch(() => ({}));
  const detail = typeof body.detail === "string" ? body.detail : `The request failed with status ${response.status}.`;
  throw new Error(detail);
}

const json = async <T>(path: string, init?: RequestInit): Promise<T> => (await checked(path, init)).json();
const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export async function* events(response: Response): AsyncGenerator<{ event: string; data: any }> {
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
  let rest = "";
  try {
    for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
      const blocks = (rest + chunk.value).split("\n\n");
      rest = blocks.pop() ?? "";
      for (const block of blocks) {
        const fields = block.split("\n").map((line) => [line.slice(0, line.indexOf(":")), line.slice(line.indexOf(":") + 1).replace(/^ /, "")]);
        const data = fields.filter(([name]) => name === "data").map(([, value]) => value);
        if (data.length) yield { event: fields.find(([name]) => name === "event")?.[1] ?? "message", data: JSON.parse(data.join("\n")) };
      }
    }
  } finally {
    reader.cancel();
  }
}

export const api = {
  me: () => json<User>("/api/me"),
  conversations: () => json<Conversation[]>("/api/conversations"),
  turns: (id: string) => json<Turn[]>(`/api/conversations/${id}`),
  forget: (id: string) => checked(`/api/conversations/${id}`, { method: "DELETE" }),
  chat: (body: Ask) => checked("/api/chat", post(body)),
  feedback: (conversation: string, helpful: boolean) => call("/api/feedback", post({ conversation, helpful })),
  promotion: () => json<Status>("/api/promotion"),
  decide: (decision: string) => json<Status>("/api/promotion", post({ decision })),
};
