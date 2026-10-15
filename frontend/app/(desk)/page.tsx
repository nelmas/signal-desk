import Link from "next/link";
import { Cites, CompanyLink, Confidence } from "@/components/bits";
import { eventLabel, longDate, shortDate, stripInlineIds, when } from "@/lib/format";
import { getDict } from "@/lib/lang";
import { getBriefing, getBriefingDates } from "@/lib/queries";

export default async function BriefingPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;
  const valid = date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : undefined;
  const { lang, t } = await getDict();
  const [briefing, dates] = await Promise.all([getBriefing(valid, lang), getBriefingDates(10)]);
  const b = t.briefing;

  if (!briefing?.content) {
    return (
      <div className="view-head">
        <span className="eyebrow">{b.eyebrow}</span>
        <h1>{b.noneTitle}</h1>
        <p>{b.noneText}</p>
      </div>
    );
  }
  const c = briefing.content;
  const direction = { up: [b.up, "up"], down: [b.down, "down"], mixed: [b.mixed, "mixed"] } as const;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">
          {b.eyebrow} · {longDate(briefing.date, lang)}
        </span>
        <h1>{c.stories[0]?.headline ?? b.fallbackTitle}</h1>
        {dates.length > 1 && (
          <nav className="datebar" aria-label={b.earlier}>
            {dates.map((d) => (
              <Link
                key={d}
                href={d === dates[0] ? "/" : `/?date=${d}`}
                aria-current={d === briefing.date ? "page" : undefined}
              >
                {shortDate(d, lang)}
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
        <p className="empty">{b.quiet}</p>
      )}

      <section className="panel holdings section">
        <header>
          <h2>{b.holdings}</h2>
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
          <p className="empty">{b.noHoldings}</p>
        )}
        {!!c.holdings_also?.length && (
          <p className="muted">
            {b.alsoInNews} {c.holdings_also.join(", ")}.
          </p>
        )}
      </section>

      {c.stories.length > 0 && (
        <section className="panel section">
          <header>
            <h2>{b.topStories}</h2>
            <span className="eyebrow">{b.ranked}</span>
          </header>
          {c.stories.map((st, i) => (
            <article className="story" key={st.story_id ?? i}>
              <div className="story-head">
                <span className="rank">{i + 1}</span>
                <h3>{st.headline}</h3>
              </div>
              <div className="chips">
                <span className="chip ev">{eventLabel(st.event_type, lang)}</span>
                <Link className="chip" href={`/stock/${encodeURIComponent(st.company)}`}>
                  {st.name}
                </Link>
              </div>
              <dl className="three">
                {(
                  [
                    [b.whatHappened, st.what_happened],
                    [b.whatItMeans, st.what_it_means],
                    [b.whatNext, st.what_next],
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
            <h2>{b.sectors}</h2>
          </header>
          <div className="sectors">
            {c.sectors.map((s) => (
              <div className="sector" key={s.name}>
                <span className={`dir ${direction[s.direction][1]}`}>{direction[s.direction][0]}</span>
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
          <h2>{b.ideas}</h2>
          <span className="eyebrow">{b.ideasEyebrow}</span>
        </header>
        {c.ideas.length ? (
          c.ideas.map((idea) => (
            <div className="idea" key={idea.company}>
              <div className="name">
                <h3>
                  <CompanyLink k={idea.company} name={idea.name} />
                </h3>
                <Confidence level={idea.confidence} t={t.confidence} />
                <span className="muted" style={{ fontSize: ".8rem" }}>
                  {b.price}:{" "}
                  {(idea.market_label && t.market[idea.market_label as keyof typeof t.market]) ||
                    idea.market}
                </span>
              </div>
              <div>
                <span className="eyebrow">{b.whyRise}</span>
                <p>
                  {idea.why_rise.text} <Cites ns={idea.why_rise.cites} />
                </p>
              </div>
              <div>
                <span className="eyebrow">{b.risks}</span>
                <p>
                  {idea.risks.text} <Cites ns={idea.risks.cites} />
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="empty">{b.noIdeas}</p>
        )}
        <p className="disclaimer">{b.disclaimer}</p>
      </section>

      {c.sources.length > 0 && (
        <section className="panel section">
          <header>
            <h2>{b.sources}</h2>
            <span className="eyebrow">{b.stockholmTimes}</span>
          </header>
          <ol className="sources">
            {c.sources.map((s) => (
              <li key={s.n} id={`src-${s.n}`} value={s.n}>
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.title}
                </a>{" "}
                · {s.source} · {when(s.published_at, lang)}
              </li>
            ))}
          </ol>
          {briefing.model && (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              {b.writtenBy(briefing.model)}
            </p>
          )}
        </section>
      )}
    </>
  );
}
