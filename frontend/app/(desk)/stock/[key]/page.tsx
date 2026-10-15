import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Cites, ScoreBar } from "@/components/bits";
import { PriceNewsChart } from "@/components/price-news-chart";
import { buildChartDays, lastDays } from "@/lib/chart";
import { explainScore } from "@/lib/explain";
import { eventLabel, num, signed, TIME_ZONE, when } from "@/lib/format";
import { getDict } from "@/lib/lang";
import { getCompany, getStockDetail } from "@/lib/queries";

type Props = { params: Promise<{ key: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const company = await getCompany(decodeURIComponent((await params).key));
  return { title: company?.name ?? "Signal Desk" };
}

const FACTORS = ["news_volume", "event_importance", "sentiment_shift"] as const;

export default async function StockPage({ params }: Props) {
  const company = await getCompany(decodeURIComponent((await params).key));
  if (!company) notFound();
  const [{ prices, coverage, score, articles }, { lang, t }] = await Promise.all([
    getStockDetail(company.id),
    getDict(),
  ]);
  const s = t.stock;

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date());
  const days = buildChartDays(lastDays(today, 60), prices, coverage);
  const last = prices.at(-1);
  const prev = prices.at(-2);
  const change = last && prev ? (last.close / prev.close - 1) * 100 : null;
  const since = new Date(Date.now() - 24 * 3600 * 1000);
  const explanation = explainScore(company.name, score?.components ?? null, articles, since, lang);
  const factors = score?.components.factors ?? {};
  const weights = score?.components.weights_used ?? {};
  const market = (score?.components.market?.label ?? "no_price_data") as keyof typeof t.market;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">
          {s.eyebrow}
          {company.sector ? ` · ${company.sector}` : ""}
          {company.holding ? ` · ${s.holding}` : company.watched ? ` · ${s.watchlist}` : ""}
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
            <span className="eyebrow">{s.lastClose}</span>
            <div className="big">
              {last ? num(last.close, 2, lang) : "–"}{" "}
              {change !== null && (
                <span className={change >= 0 ? "up" : "down"} style={{ fontSize: "1rem" }}>
                  {signed(change, 1, lang)} %
                </span>
              )}
            </div>
          </div>
          <div>
            <span className="eyebrow">{s.score}</span>
            <div className="big">{score ? score.score.toFixed(0) : "–"}</div>
          </div>
        </div>
        {company.note && <p className="muted">{company.note}</p>}
      </div>

      <section className="panel section">
        <header>
          <h2>{s.chartTitle}</h2>
          <span className="eyebrow">{s.last60}</span>
        </header>
        <PriceNewsChart days={days} currency={company.currency} lang={lang} />
      </section>

      <div className="split">
        <section className="panel section">
          <header>
            <h2>{s.breakdown}</h2>
            {score && <span className="eyebrow">{score.date}</span>}
          </header>
          {score ? (
            <div className="factors">
              {FACTORS.map((key) => {
                const value = factors[key]?.score ?? 0;
                const w = weights[key];
                return (
                  <div className="factor" key={key}>
                    <div className="row">
                      <span>
                        {s.factors[key]}
                        {w !== undefined && <span className="muted"> · {(w * 100).toFixed(0)} %</span>}
                      </span>
                      <b>{value.toFixed(0)}</b>
                    </div>
                    <ScoreBar value={value} label={`${s.factors[key]}: ${value.toFixed(0)} / 100`} />
                  </div>
                );
              })}
              <div className="factor">
                <div className="row">
                  <span>{s.priceReaction}</span>
                  <b>{t.market[market] ?? market}</b>
                </div>
              </div>
            </div>
          ) : (
            <p className="empty">{s.noScore}</p>
          )}
        </section>

        <section className="panel section explain">
          <header>
            <h2>{s.why}</h2>
            <span className="eyebrow">{s.whyEyebrow}</span>
          </header>
          {explanation.sentences.map((sentence, i) => (
            <p key={i}>
              {sentence.text} <Cites ns={sentence.cites} prefix="why" />
            </p>
          ))}
          {explanation.sources.length > 0 && (
            <ol className="sources">
              {explanation.sources.map((src) => (
                <li key={src.n} id={`why-${src.n}`} value={src.n}>
                  <a href={src.url} target="_blank" rel="noopener noreferrer">
                    {src.title}
                  </a>{" "}
                  · {src.source} · {when(src.published_at, lang)}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <section className="panel section">
        <header>
          <h2>{s.recent}</h2>
          <span className="eyebrow">{s.last30}</span>
        </header>
        {articles.length === 0 ? (
          <p className="empty">{s.noRecent}</p>
        ) : (
          <ul className="feed">
            {articles.map((a) => (
              <li key={a.id}>
                <time dateTime={a.published_at}>{when(a.published_at, lang)}</time>
                <div>
                  <a className="t" href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                  {a.ai_summary && <p className="s">{a.ai_summary}</p>}
                  <div className="m chips">
                    <span className={`src${a.is_press_release ? " pr" : ""}`}>{a.source}</span>
                    {a.event_type && <span className="chip ev">{eventLabel(a.event_type, lang)}</span>}
                    {a.basis && (
                      <span className="chip">{t.basis[a.basis as keyof typeof t.basis] ?? a.basis}</span>
                    )}
                    {a.role === "affected" && <span className="chip">{s.affected}</span>}
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
