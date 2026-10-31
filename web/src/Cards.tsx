import { Check } from "lucide-react";
import type { Call, Card, Health, Status } from "./api";

const ASKS: Record<string, (args: Record<string, unknown>) => string> = {
  start_retraining: () => "Retrain on the latest fleet data: prepare, train, evaluate and register, on serverless compute.",
  start_promotion: (args) => `Start promoting model ${args.version}: shadow, canary at 10 %, then 100 %, each step approved by you.`,
  rollback: () => "Roll back the promotion in progress: the previous model goes back to 100 % of live traffic.",
};
const BUTTONS: Record<Card["step"], [string, string][]> = {
  first: [["approve", "Deploy"], ["rollback", "Cancel"]],
  shadow: [["approve", "Start canary"], ["rollback", "Stop shadow"]],
  canary: [["promote", "Promote to 100 %"], ["rollback", "Roll back"]],
  window: [["close", "Close window"], ["rollback", "Roll back"]],
};

const share = (value: unknown) => (typeof value === "number" ? `${(value * 100).toFixed(1)} %` : "–");

function Buttons({ choices, act, ready = true }: { choices: [string, string][]; act?: (word: string) => void; ready?: boolean }) {
  return (
    <div className="buttons">
      {choices.map(([word, label], index) => (
        <button key={word} className={index ? "secondary" : "primary"} disabled={!act || (!index && !ready)} onClick={() => act?.(word)}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function Approval({ calls, decided, act }: { calls: Call[]; decided?: boolean; act?: (approve: boolean) => void }) {
  return (
    <article className="card" aria-label="Approval">
      <h3>Your approval</h3>
      <ul>
        {calls.map((call) => (
          <li key={call.id}>{(ASKS[call.tool] ?? (() => call.tool))(call.arguments)}</li>
        ))}
      </ul>
      {decided === undefined ? (
        <Buttons choices={[["approve", "Approve"], ["decline", "Decline"]]} act={act && ((word) => act(word === "approve"))} />
      ) : (
        <p className="status">
          {decided && <Check size={16} className="ok" aria-hidden />}
          {decided ? "Approved" : "Declined"}
        </p>
      )}
    </article>
  );
}

function Compare({ facts, plan }: Card) {
  const [offline, champion, challenger]: [Record<string, number>, Health, Health] = [facts.offline, facts.champion, facts.challenger];
  const rows = [
    ["Recall at 7 days, same holdout", share(offline.champion_recall), share(offline.recall)],
    ["Precision at 7 days, same holdout", share(offline.champion_precision), share(offline.precision)],
    ["Requests", champion.requests, challenger.requests],
    ["Failed", champion.failed, challenger.failed],
    ["p95 latency", `${Math.round(champion.p95_ms)} ms`, `${Math.round(challenger.p95_ms)} ms`],
    ["Agreement with the champion", "–", share(challenger.agreement)],
  ];
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Measure</th>
          <th scope="col">Model {plan.champion} · champion</th>
          <th scope="col">Model {plan.challenger} · challenger</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([name, ...values]) => (
          <tr key={String(name)}>
            <th scope="row">{name}</th>
            {values.map((value, index) => (
              <td key={index}>{value}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Body(card: Card) {
  const { step, plan, facts } = card;
  if (step === "first") return <p>Model {plan.challenger} would be the first model: recall {share(facts.recall)}, precision {share(facts.precision)} on its holdout.</p>;
  if (step === "shadow") return <Compare {...card} />;
  if (step === "window") return <p>Model {plan.challenger} serves 100 % of live traffic. Model {facts.rollback_to} comes back in one step until you close the window.</p>;
  return (
    <p>
      Model {plan.challenger} serves 10 % of live traffic. {facts.checks} health checks in {facts.elapsed ?? 0} minutes
      {facts.requests !== undefined && `: ${facts.requests} requests, ${facts.failed} failed, p95 ${Math.round(facts.p95_ms)} ms`}.
    </p>
  );
}

const TITLES: Record<Card["step"], string> = { first: "First model", shadow: "Shadow comparison", canary: "Canary at 10 %", window: "Rollback window" };
const WAIT: Partial<Record<Card["step"], string>> = {
  shadow: "Not ready yet: the shadow needs more mirrored requests. Start canary checks it again.",
  canary: "Checked every minute. Promote opens after enough healthy checks; a failed check rolls back at once.",
};

export function Promotion({ status, live, act }: { status: Status; live: boolean; act?: (word: string) => void }) {
  const { outcome, card } = status;
  const ready = card?.facts.ready ?? true;
  return (
    <article className="card" aria-label="Promotion">
      {outcome && <p className="status">{outcome}</p>}
      {card && (
        <>
          <h3>
            {TITLES[card.step]} <small>model {card.plan.challenger}</small>
          </h3>
          <Body {...card} />
          {!ready && WAIT[card.step] && <p className="status">{WAIT[card.step]}</p>}
          {ready && card.step === "canary" && (
            <p className="status">
              <Check size={16} className="ok" aria-hidden /> Healthy and ready for 100 %.
            </p>
          )}
          {live && <Buttons choices={BUTTONS[card.step]} act={act} ready={ready || card.step !== "canary"} />}
        </>
      )}
    </article>
  );
}
