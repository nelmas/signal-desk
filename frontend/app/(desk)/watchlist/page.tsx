import type { Metadata } from "next";
import Link from "next/link";
import { CompanyLink, ScoreBar } from "@/components/bits";
import { longDate } from "@/lib/format";
import { getDict } from "@/lib/lang";
import { getScores } from "@/lib/queries";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDict()).t.nav.watchlist };
}

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const { show } = await searchParams;
  const mine = show === "mine";
  const [{ date, rows: all }, { lang, t }] = await Promise.all([getScores(60), getDict()]);
  const rows = mine ? all.filter((r) => r.watched) : all.slice(0, 40);
  const w = t.watchlist;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">
          {w.eyebrow}
          {date ? ` · ${longDate(date, lang)}` : ""}
        </span>
        <h1>{w.title}</h1>
        <p>{w.intro}</p>
      </div>
      <div className="filters" role="group">
        <Link href="/watchlist" aria-current={!mine ? "true" : undefined}>
          {w.all}
        </Link>
        <Link href="/watchlist?show=mine" aria-current={mine ? "true" : undefined}>
          {w.mine}
        </Link>
      </div>
      <div className="panel tbl-wrap">
        {rows.length === 0 ? (
          <p className="empty">{w.empty}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>{w.cols.stock}</th>
                <th>{w.cols.score}</th>
                <th className="num">{w.cols.articles}</th>
                <th className="num">{w.cols.volume}</th>
                <th className="num">{w.cols.importance}</th>
                <th className="num">{w.cols.tone}</th>
                <th>{w.cols.price}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const f = r.components.factors;
                const label = (r.components.market?.label ?? "no_price_data") as keyof typeof t.market;
                return (
                  <tr key={r.key}>
                    <td className="mono">{i + 1}</td>
                    <td>
                      <CompanyLink k={r.key} name={r.name} />
                      <div className="chips">
                        {r.symbol && <span className="ticker">{r.symbol}</span>}
                        {r.holding && <span className="chip hold">{w.holding}</span>}
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
                        {t.market[label] ?? label}
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
