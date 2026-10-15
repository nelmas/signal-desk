import type { Metadata } from "next";
import Link from "next/link";
import { CompanyLink, ScoreBar } from "@/components/bits";
import { longDate, MARKET_LABEL } from "@/lib/format";
import { getScores } from "@/lib/queries";

export const metadata: Metadata = { title: "Signal watchlist" };

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const { show } = await searchParams;
  const mine = show === "mine";
  const { date, rows: all } = await getScores(60);
  const rows = mine ? all.filter((r) => r.watched) : all.slice(0, 40);

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">Signal watchlist{date ? ` · ${longDate(date)}` : ""}</span>
        <h1>Highest signal scores today</h1>
        <p>
          The 0–100 score is plain arithmetic, not AI: news volume against normal, how important
          the events are, and how far the tone has shifted. How the share price reacted is shown
          beside it, not mixed in.
        </p>
      </div>
      <div className="filters" role="group" aria-label="Show">
        <Link href="/watchlist" aria-current={!mine ? "true" : undefined}>
          All companies
        </Link>
        <Link href="/watchlist?show=mine" aria-current={mine ? "true" : undefined}>
          My watchlist
        </Link>
      </div>
      <div className="panel tbl-wrap">
        {rows.length === 0 ? (
          <p className="empty">No scores yet. They appear after the first hourly run with news.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Stock</th>
                <th>Signal score</th>
                <th className="num">Articles 24h</th>
                <th className="num">Volume</th>
                <th className="num">Importance</th>
                <th className="num">Tone shift</th>
                <th>Price</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const f = r.components.factors;
                const label = r.components.market?.label ?? "no_price_data";
                return (
                  <tr key={r.key}>
                    <td className="mono">{i + 1}</td>
                    <td>
                      <CompanyLink k={r.key} name={r.name} />
                      <div className="chips">
                        {r.symbol && <span className="ticker">{r.symbol}</span>}
                        {r.holding && <span className="chip hold">Holding</span>}
                      </div>
                    </td>
                    <td>
                      <div className="scorecell">
                        <ScoreBar value={r.score} />
                        <span className="scoreval">{r.score.toFixed(0)}</span>
                      </div>
                    </td>
                    <td className="num mono">{f.news_volume?.articles_24h ?? 0}</td>
                    <td className="num mono">{(f.news_volume?.score ?? 0).toFixed(0)}</td>
                    <td className="num mono">{(f.event_importance?.score ?? 0).toFixed(0)}</td>
                    <td className="num mono">{(f.sentiment_shift?.score ?? 0).toFixed(0)}</td>
                    <td>
                      <span
                        className={`chip${label === "moving_with_news" ? " pos" : ""}${label === "moving_against_news" ? " neg" : ""}`}
                      >
                        {MARKET_LABEL[label] ?? label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
