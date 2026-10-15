import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Cites, ScoreBar } from "@/components/bits";
import { PriceNewsChart } from "@/components/price-news-chart";
import { buildChartDays, lastDays } from "@/lib/chart";
import { explainScore } from "@/lib/explain";
import { BASIS_LABEL, humanize, MARKET_LABEL, signed, TIME_ZONE, when } from "@/lib/format";
import { getCompany, getStockDetail } from "@/lib/queries";

type Props = { params: Promise<{ key: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const company = await getCompany(decodeURIComponent((await params).key));
  return { title: company?.name ?? "Stock" };
}

const FACTORS = [
  ["news_volume", "News volume"],
  ["event_importance", "Event importance"],
  ["sentiment_shift", "Tone shift"],
] as const;

export default async function StockPage({ params }: Props) {
  const company = await getCompany(decodeURIComponent((await params).key));
  if (!company) notFound();
  const { prices, coverage, score, articles } = await getStockDetail(company.id);

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date());
  const days = buildChartDays(lastDays(today, 60), prices, coverage);
  const last = prices.at(-1);
  const prev = prices.at(-2);
  const change = last && prev ? (last.close / prev.close - 1) * 100 : null;
  const since = new Date(Date.now() - 24 * 3600 * 1000);
  const explanation = explainScore(company.name, score?.components ?? null, articles, since);
  const factors = score?.components.factors ?? {};
  const weights = score?.components.weights_used ?? {};
  const market = score?.components.market;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">
          Stock{company.sector ? ` · ${company.sector}` : ""}
          {company.holding ? " · Holding" : company.watched ? " · Watchlist" : ""}
        </span>
        <div className="stock-top">
          <div>
            <h1>{company.name}</h1>
            {company.symbol && (
              <span className="ticker">
                {company.symbol} · {company.mic} {company.currency ? `· ${company.currency}` : ""}
              </span>
            )}
          </div>
          <div>
            <span className="eyebrow">Last close</span>
            <div className="big">
              {last ? last.close.toFixed(2) : "–"}{" "}
              {change !== null && (
                <span className={change >= 0 ? "up" : "down"} style={{ fontSize: "1rem" }}>
                  {signed(change)}%
                </span>
              )}
            </div>
          </div>
          <div>
            <span className="eyebrow">Signal score</span>
            <div className="big">{score ? score.score.toFixed(0) : "–"}</div>
          </div>
        </div>
        {company.note && <p className="muted">{company.note}</p>}
      </div>

      <section className="panel section">
        <header>
          <h2>Price and news coverage</h2>
          <span className="eyebrow">Last 60 days</span>
        </header>
        <PriceNewsChart days={days} currency={company.currency} />
      </section>

      <div className="split">
        <section className="panel section">
          <header>
            <h2>Score breakdown</h2>
            {score && <span className="eyebrow">{score.date}</span>}
          </header>
          {score ? (
            <div className="factors">
              {FACTORS.map(([key, name]) => {
                const value = factors[key]?.score ?? 0;
                const w = weights[key];
                return (
                  <div className="factor" key={key}>
                    <div className="row">
                      <span>
                        {name}
                        {w !== undefined && <span className="muted"> · {(w * 100).toFixed(0)}%</span>}
                      </span>
                      <b>{value.toFixed(0)}</b>
                    </div>
                    <ScoreBar value={value} label={`${name}: ${value.toFixed(0)} of 100`} />
                  </div>
                );
              })}
              <div className="factor">
                <div className="row">
                  <span>Price reaction (not in the score)</span>
                  <b>{MARKET_LABEL[market?.label ?? "no_price_data"] ?? market?.label}</b>
                </div>
              </div>
            </div>
          ) : (
            <p className="empty">No score: no tagged news about this company recently.</p>
          )}
        </section>

        <section className="panel section explain">
          <header>
            <h2>Why it&apos;s on the list</h2>
            <span className="eyebrow">From the score&apos;s inputs</span>
          </header>
          {explanation.sentences.map((s, i) => (
            <p key={i}>
              {s.text} <Cites ns={s.cites} prefix="why" />
            </p>
          ))}
          {explanation.sources.length > 0 && (
            <ol className="sources">
              {explanation.sources.map((s) => (
                <li key={s.n} id={`why-${s.n}`} value={s.n}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.title}
                  </a>{" "}
                  · {s.source} · {when(s.published_at)}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <section className="panel section">
        <header>
          <h2>Recent news</h2>
          <span className="eyebrow">Last 30 days</span>
        </header>
        {articles.length === 0 ? (
          <p className="empty">No tagged articles in the last 30 days.</p>
        ) : (
          <ul className="feed">
            {articles.map((a) => (
              <li key={a.id}>
                <time dateTime={a.published_at}>{when(a.published_at)}</time>
                <div>
                  <a className="t" href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                  {a.ai_summary && <p className="s">{a.ai_summary}</p>}
                  <div className="m chips">
                    <span className={`src${a.is_press_release ? " pr" : ""}`}>{a.source}</span>
                    {a.event_type && <span className="chip ev">{humanize(a.event_type)}</span>}
                    {a.basis && <span className="chip">{BASIS_LABEL[a.basis] ?? a.basis}</span>}
                    {a.role === "affected" && <span className="chip">Affected, not the subject</span>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
