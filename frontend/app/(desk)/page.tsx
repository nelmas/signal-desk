import Link from "next/link";
import { Cites, CompanyLink, Confidence } from "@/components/bits";
import { humanize, longDate, shortDate, stripInlineIds, when } from "@/lib/format";
import { getBriefing, getBriefingDates } from "@/lib/queries";

const DIRECTION = {
  up: { text: "↑ More attention, better news", cls: "up" },
  down: { text: "↓ Worse news", cls: "down" },
  mixed: { text: "→ Mixed", cls: "mixed" },
} as const;

export default async function BriefingPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;
  const valid = date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : undefined;
  const [briefing, dates] = await Promise.all([getBriefing(valid), getBriefingDates(10)]);

  if (!briefing?.content) {
    return (
      <div className="view-head">
        <span className="eyebrow">Morning briefing</span>
        <h1>No briefing yet</h1>
        <p>The first one is written on the first hourly run after the morning send time.</p>
      </div>
    );
  }
  const c = briefing.content;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">Morning briefing · {longDate(briefing.date)}</span>
        <h1>{c.stories[0]?.headline ?? "Today's briefing"}</h1>
        {dates.length > 1 && (
          <nav className="datebar" aria-label="Earlier briefings">
            {dates.map((d) => (
              <Link
                key={d}
                href={d === dates[0] ? "/" : `/?date=${d}`}
                aria-current={d === briefing.date ? "page" : undefined}
              >
                {shortDate(d)}
              </Link>
            ))}
          </nav>
        )}
      </div>

      {c.overview.text ? (
        <p className="overview">
          {stripInlineIds(c.overview.text)} <Cites ns={c.overview.cites} />
        </p>
      ) : (
        <p className="empty">A quiet window: no news strong enough for an overview.</p>
      )}

      <section className="panel holdings section">
        <header>
          <h2>News about your holdings</h2>
        </header>
        {c.holdings.length ? (
          <ul className="hold-list">
            {c.holdings.map((h) => (
              <li key={h.company}>
                <span className="who">
                  <CompanyLink k={h.company} name={h.name} />
                  {h.share && <span className="via">{h.share}</span>}
                </span>
                <span>
                  {h.text} <Cites ns={h.cites} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">No news about your holdings.</p>
        )}
        {!!c.holdings_also?.length && (
          <p className="muted">Also in the news: {c.holdings_also.join(", ")}.</p>
        )}
      </section>

      {c.stories.length > 0 && (
        <section className="panel section">
          <header>
            <h2>Top stories</h2>
            <span className="eyebrow">Ranked by importance</span>
          </header>
          {c.stories.map((st, i) => (
            <article className="story" key={st.story_id ?? i}>
              <div className="story-head">
                <span className="rank">{i + 1}</span>
                <h3>{st.headline}</h3>
              </div>
              <div className="chips">
                <span className="chip ev">{humanize(st.event_type)}</span>
                <Link className="chip" href={`/stock/${encodeURIComponent(st.company)}`}>
                  {st.name}
                </Link>
              </div>
              <dl className="three">
                {(
                  [
                    ["What happened", st.what_happened],
                    ["What it means", st.what_it_means],
                    ["What it could lead to", st.what_next],
                  ] as const
                ).map(([label, part]) =>
                  part.text ? (
                    <div key={label}>
                      <dt className="eyebrow">{label}</dt>
                      <dd>
                        {stripInlineIds(part.text)} <Cites ns={part.cites} />
                      </dd>
                    </div>
                  ) : null,
                )}
              </dl>
            </article>
          ))}
        </section>
      )}

      {c.sectors.length > 0 && (
        <section className="panel section">
          <header>
            <h2>Sectors to keep an eye on</h2>
          </header>
          <div className="sectors">
            {c.sectors.map((s) => (
              <div className="sector" key={s.name}>
                <span className={`dir ${DIRECTION[s.direction].cls}`}>
                  {DIRECTION[s.direction].text}
                </span>
                <h3>{s.name}</h3>
                <p>
                  {s.reason} <Cites ns={s.cites} />
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel section">
        <header>
          <h2>Stocks that could benefit</h2>
          <span className="eyebrow">Ideas to research</span>
        </header>
        {c.ideas.length ? (
          c.ideas.map((idea) => (
            <div className="idea" key={idea.company}>
              <div className="name">
                <h3>
                  <CompanyLink k={idea.company} name={idea.name} />
                </h3>
                <Confidence level={idea.confidence} />
                <span className="muted" style={{ fontSize: ".8rem" }}>
                  Price: {idea.market}
                </span>
              </div>
              <div>
                <span className="eyebrow">Why it could rise</span>
                <p>
                  {idea.why_rise.text} <Cites ns={idea.why_rise.cites} />
                </p>
              </div>
              <div>
                <span className="eyebrow">What could go wrong</span>
                <p>
                  {idea.risks.text} <Cites ns={idea.risks.cites} />
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="empty">No idea met the bar today.</p>
        )}
        <p className="disclaimer">{c.disclaimer}</p>
      </section>

      {c.sources.length > 0 && (
        <section className="panel section">
          <header>
            <h2>Sources</h2>
            <span className="eyebrow">Times in Stockholm</span>
          </header>
          <ol className="sources">
            {c.sources.map((s) => (
              <li key={s.n} id={`src-${s.n}`} value={s.n}>
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.title}
                </a>{" "}
                · {s.source} · {when(s.published_at)}
              </li>
            ))}
          </ol>
          {briefing.model && (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Written by {briefing.model}, checked by code: every claim above cites an article the
              model was given.
            </p>
          )}
        </section>
      )}
    </>
  );
}
