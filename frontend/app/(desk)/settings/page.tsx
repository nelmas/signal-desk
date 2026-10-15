import type { Metadata } from "next";
import Link from "next/link";
import { getSettingsData, searchCompanies } from "@/lib/settings";
import {
  addToWatchlist,
  editWatch,
  removeFromWatchlist,
  saveBriefing,
  saveEmail,
  saveSources,
  saveWeights,
} from "./actions";

export const metadata: Metadata = { title: "Settings" };

const SAVED: Record<string, string> = {
  weights: "Score weights saved. They apply from the next hourly run.",
  briefing: "Briefing settings saved. They apply from the next briefing.",
  email: "Email settings saved.",
  sources: "Sources and markets saved. They apply from the next hourly run.",
  watchlist: "Watchlist updated.",
};

const FACTOR_NAMES = {
  news_volume: ["News volume", "How much more news than the company's usual day"],
  event_importance: ["Event importance", "How important the biggest event is"],
  sentiment_shift: ["Tone shift", "How far the tone moved from the company's usual"],
} as const;

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string; error?: string; q?: string }>;
}) {
  const { saved, error, q } = await searchParams;
  const [s, hits] = await Promise.all([getSettingsData(), searchCompanies(q ?? "")]);

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">Settings</span>
        <h1>Make the briefing yours</h1>
      </div>
      {saved && SAVED[saved] && <p className="notice" role="status">{SAVED[saved]}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      <section className="panel section" id="briefing">
        <header><h2>Morning briefing</h2></header>
        <form action={saveBriefing} className="form">
          <div className="form-row">
            <label htmlFor="send_time">Write and send it at</label>
            <input id="send_time" name="send_time" type="time" defaultValue={s.briefing.send_time} required />
            <span className="help">Stockholm time. Many Swedish companies publish 07:00–08:00; 08:30 catches them before the 09:00 open.</span>
          </div>
          <div className="form-row">
            <label htmlFor="language">Language</label>
            <select id="language" name="language" defaultValue={s.briefing.language}>
              <option value="en">English</option>
              <option value="sv">Svenska</option>
            </select>
          </div>
          <div className="form-row">
            <label htmlFor="max_stories">Top stories</label>
            <input id="max_stories" name="max_stories" type="number" min={3} max={8} defaultValue={s.briefing.max_stories} />
          </div>
          <div className="form-row">
            <label htmlFor="max_ideas">Stock ideas, at most</label>
            <input id="max_ideas" name="max_ideas" type="number" min={0} max={5} defaultValue={s.briefing.max_ideas} />
            <span className="help">0 turns the ideas section off.</span>
          </div>
          <button className="btn" type="submit">Save briefing settings</button>
        </form>
      </section>

      <section className="panel section" id="email">
        <header><h2>Daily email</h2></header>
        <form action={saveEmail} className="form">
          <label className="toggle">
            <input type="checkbox" name="enabled" defaultChecked={s.email.enabled} />
            <span>Email me the briefing when it is written</span>
          </label>
          <div className="form-row">
            <label htmlFor="to">Send to</label>
            <input id="to" name="to" type="email" defaultValue={s.email.to} placeholder="you@example.com" />
            <span className="help">With Resend&apos;s free plan this must be the address you signed up to Resend with.</span>
          </div>
          <button className="btn" type="submit">Save email settings</button>
        </form>
      </section>

      <section className="panel section" id="watchlist">
        <header>
          <h2>Watchlist and holdings</h2>
          <span className="eyebrow">{s.watchlist.length} stocks</span>
        </header>
        <p className="muted">
          Holdings get their own section at the top of the briefing. A note like
          “Via my fund, 5.7% of fund” shows the share there.
        </p>
        {s.watchlist.length > 0 && (
          <ul className="watch-list">
            {s.watchlist.map((w) => (
              <li key={w.company_id}>
                <form action={editWatch} className="watch-row">
                  <input type="hidden" name="company_id" value={w.company_id} />
                  <span className="who">
                    <Link href={`/stock/${encodeURIComponent(w.key)}`}>{w.name}</Link>
                    {w.symbol && <span className="ticker"> {w.symbol}</span>}
                  </span>
                  <label className="toggle">
                    <input type="checkbox" name="holding" defaultChecked={w.holding} /> Holding
                  </label>
                  <input name="note" defaultValue={w.note ?? ""} placeholder="Note" aria-label={`Note for ${w.name}`} maxLength={200} />
                  <button className="btn small" type="submit">Save</button>
                  <button className="linkish" type="submit" formAction={removeFromWatchlist}>Remove</button>
                </form>
              </li>
            ))}
          </ul>
        )}
        <form action="/settings#watchlist" className="search">
          <label htmlFor="q">Add a stock</label>
          <input id="q" name="q" type="search" defaultValue={q ?? ""} placeholder="Name or symbol, e.g. Volvo or AAPL" />
          <button className="btn small" type="submit">Search</button>
        </form>
        {q && hits.length === 0 && <p className="empty">No listed company matches “{q}”.</p>}
        {hits.length > 0 && (
          <ul className="watch-list">
            {hits.map((h) => (
              <li key={h.id} className="watch-row">
                <span className="who">
                  {h.name} {h.symbol && <span className="ticker">{h.symbol} · {h.mic}</span>}
                </span>
                {h.watched ? (
                  <span className="muted">On your watchlist</span>
                ) : (
                  <form action={addToWatchlist} className="inline">
                    <input type="hidden" name="company_id" value={h.id} />
                    <label className="toggle"><input type="checkbox" name="holding" /> I own it</label>
                    <button className="btn small" type="submit">Add</button>
                  </form>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel section" id="weights">
        <header><h2>Signal score weights</h2></header>
        <p className="muted">How much each factor counts. They are rescaled to add up to 100%.</p>
        <form action={saveWeights} className="form">
          {(Object.keys(FACTOR_NAMES) as (keyof typeof FACTOR_NAMES)[]).map((k) => (
            <div className="form-row" key={k}>
              <label htmlFor={k}>{FACTOR_NAMES[k][0]}</label>
              <input id={k} name={k} type="number" min={0} max={100} step={1}
                defaultValue={Math.round(s.weights[k] * 100)} />
              <span className="help">{FACTOR_NAMES[k][1]}</span>
            </div>
          ))}
          <button className="btn" type="submit">Save weights</button>
        </form>
      </section>

      <section className="panel section" id="sources">
        <header><h2>News sources and markets</h2></header>
        <form action={saveSources} className="form">
          <fieldset>
            <legend className="eyebrow">Markets</legend>
            {s.markets.map((m) => (
              <label className="toggle" key={m.key}>
                <input type="checkbox" name={`on_market_${m.key}`} defaultChecked={m.on} /> {m.name}
              </label>
            ))}
            <span className="help">Turning a market off skips its sources and leaves its stories out of the briefing. Your holdings are always reported.</span>
          </fieldset>
          <fieldset>
            <legend className="eyebrow">Sources</legend>
            {s.sources.map((src) => (
              <label className="toggle" key={src.key}>
                <input type="checkbox" name={`on_${src.key}`} defaultChecked={src.on} /> {src.name}
                {src.market && <span className="muted"> · {src.market}</span>}
              </label>
            ))}
          </fieldset>
          <button className="btn" type="submit">Save sources</button>
        </form>
      </section>
    </>
  );
}
