import type { Metadata } from "next";
import Link from "next/link";
import { getDict } from "@/lib/lang";
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

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDict()).t.nav.settings };
}

const FACTORS = ["news_volume", "event_importance", "sentiment_shift"] as const;

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string; error?: string; q?: string }>;
}) {
  const { saved, error, q } = await searchParams;
  const [s, hits, { t }] = await Promise.all([getSettingsData(), searchCompanies(q ?? ""), getDict()]);
  const st = t.settings;
  // Only known messages are shown: nothing from the address bar is echoed back.
  const savedText = saved ? st.saved[saved] : undefined;
  const errorText = error ? st.errors[error] : undefined;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">{st.eyebrow}</span>
        <h1>{st.title}</h1>
      </div>
      {savedText && <p className="notice" role="status">{savedText}</p>}
      {errorText && <p className="error" role="alert">{errorText}</p>}

      <section className="panel section" id="briefing">
        <header><h2>{st.briefingTitle}</h2></header>
        <form action={saveBriefing} className="form">
          <div className="form-row">
            <label htmlFor="send_time">{st.sendAt}</label>
            <input id="send_time" name="send_time" type="time" defaultValue={s.briefing.send_time} required />
            <span className="help">{st.sendAtHelp}</span>
          </div>
          <div className="form-row">
            <label htmlFor="language">{st.language}</label>
            <select id="language" name="language" defaultValue={s.briefing.language}>
              <option value="en">English</option>
              <option value="sv">Svenska</option>
            </select>
          </div>
          <div className="form-row">
            <label htmlFor="max_stories">{st.stories}</label>
            <input id="max_stories" name="max_stories" type="number" min={3} max={8} defaultValue={s.briefing.max_stories} />
          </div>
          <div className="form-row">
            <label htmlFor="max_ideas">{st.ideas}</label>
            <input id="max_ideas" name="max_ideas" type="number" min={0} max={5} defaultValue={s.briefing.max_ideas} />
            <span className="help">{st.ideasHelp}</span>
          </div>
          <button className="btn" type="submit">{st.saveBriefing}</button>
        </form>
      </section>

      <section className="panel section" id="email">
        <header><h2>{st.emailTitle}</h2></header>
        <form action={saveEmail} className="form">
          <label className="toggle">
            <input type="checkbox" name="enabled" defaultChecked={s.email.enabled} />
            <span>{st.emailOn}</span>
          </label>
          <div className="form-row">
            <label htmlFor="to">{st.sendTo}</label>
            <input id="to" name="to" type="email" defaultValue={s.email.to} placeholder="you@example.com" />
            <span className="help">{st.sendToHelp}</span>
          </div>
          <button className="btn" type="submit">{st.saveEmail}</button>
        </form>
      </section>

      <section className="panel section" id="watchlist">
        <header>
          <h2>{st.watchTitle}</h2>
          <span className="eyebrow">{st.stocksCount(s.watchlist.length)}</span>
        </header>
        <p className="muted">{st.watchIntro}</p>
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
                    <input type="checkbox" name="holding" defaultChecked={w.holding} /> {st.holding}
                  </label>
                  <input name="note" defaultValue={w.note ?? ""} placeholder={st.note} aria-label={`${st.note}: ${w.name}`} maxLength={200} />
                  <button className="btn small" type="submit">{st.save}</button>
                  <button className="linkish" type="submit" formAction={removeFromWatchlist}>{st.remove}</button>
                </form>
              </li>
            ))}
          </ul>
        )}
        <form action="/settings#watchlist" className="search">
          <label htmlFor="q">{st.addStock}</label>
          <input id="q" name="q" type="search" defaultValue={q ?? ""} placeholder={st.searchPlaceholder} />
          <button className="btn small" type="submit">{st.search}</button>
        </form>
        {q && hits.length === 0 && <p className="empty">{st.noMatch(q)}</p>}
        {hits.length > 0 && (
          <ul className="watch-list">
            {hits.map((h) => (
              <li key={h.id} className="watch-row">
                <span className="who">
                  {h.name} {h.symbol && <span className="ticker">{h.symbol} · {h.mic}</span>}
                </span>
                {h.watched ? (
                  <span className="muted">{st.onList}</span>
                ) : (
                  <form action={addToWatchlist} className="inline">
                    <input type="hidden" name="company_id" value={h.id} />
                    <label className="toggle"><input type="checkbox" name="holding" /> {st.iOwn}</label>
                    <button className="btn small" type="submit">{st.add}</button>
                  </form>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel section" id="weights">
        <header><h2>{st.weightsTitle}</h2></header>
        <p className="muted">{st.weightsIntro}</p>
        <form action={saveWeights} className="form">
          {FACTORS.map((k) => (
            <div className="form-row" key={k}>
              <label htmlFor={k}>{t.stock.factors[k]}</label>
              <input id={k} name={k} type="number" min={0} max={100} step={1}
                defaultValue={Math.round(s.weights[k] * 100)} />
              <span className="help">{st.factorHelp[k]}</span>
            </div>
          ))}
          <button className="btn" type="submit">{st.saveWeights}</button>
        </form>
      </section>

      <section className="panel section" id="sources">
        <header><h2>{st.sourcesTitle}</h2></header>
        <form action={saveSources} className="form">
          <fieldset>
            <legend className="eyebrow">{st.markets}</legend>
            {s.markets.map((m) => (
              <label className="toggle" key={m.key}>
                <input type="checkbox" name={`on_market_${m.key}`} defaultChecked={m.on} />{" "}
                {st.marketNames[m.key] ?? m.name}
              </label>
            ))}
            <span className="help">{st.marketsHelp}</span>
          </fieldset>
          <fieldset>
            <legend className="eyebrow">{st.sources}</legend>
            {s.sources.map((src) => (
              <label className="toggle" key={src.key}>
                <input type="checkbox" name={`on_${src.key}`} defaultChecked={src.on} /> {src.name}
                {src.market && <span className="muted"> · {src.market}</span>}
              </label>
            ))}
          </fieldset>
          <button className="btn" type="submit">{st.saveSources}</button>
        </form>
      </section>
    </>
  );
}
