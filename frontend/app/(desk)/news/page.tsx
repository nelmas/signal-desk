import type { Metadata } from "next";
import Link from "next/link";
import { humanize, BASIS_LABEL, when } from "@/lib/format";
import { makeCursor } from "@/lib/paging";
import { getNews, NEWS_PAGE, type NewsFilter } from "@/lib/queries";

export const metadata: Metadata = { title: "News feed" };

type Params = { kind?: string; scope?: string; q?: string; before?: string };

function href(p: Params): string {
  const qs = new URLSearchParams(
    Object.entries(p).filter((e): e is [string, string] => !!e[1] && e[1] !== "all"),
  );
  const s = qs.toString();
  return s ? `/news?${s}` : "/news";
}

export default async function NewsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const p = await searchParams;
  const filter: NewsFilter = {
    kind: p.kind === "pr" || p.kind === "news" ? p.kind : "all",
    scope: p.scope === "all" ? "all" : "tagged",
    q: (p.q ?? "").slice(0, 80),
    before: p.before ?? null,
  };
  const rows = await getNews(filter);
  const items = rows.slice(0, NEWS_PAGE);
  const base = { kind: filter.kind, scope: filter.scope === "all" ? "all" : undefined, q: filter.q };

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">News feed</span>
        <h1>Everything collected</h1>
        <p>
          Headline, a short excerpt and a link to the source. By default only articles about a
          company on the list; switch to “All articles” to see everything the feeds delivered.
        </p>
      </div>
      <div className="filters" role="group" aria-label="Filter">
        {(
          [
            ["all", "All"],
            ["pr", "Press releases"],
            ["news", "News"],
          ] as const
        ).map(([k, label]) => (
          <Link key={k} href={href({ ...base, kind: k })} aria-current={filter.kind === k ? "true" : undefined}>
            {label}
          </Link>
        ))}
        <Link
          href={href({ ...base, scope: filter.scope === "all" ? undefined : "all" })}
          aria-current={filter.scope === "all" ? "true" : undefined}
        >
          All articles
        </Link>
        <form action="/news">
          {filter.kind !== "all" && <input type="hidden" name="kind" value={filter.kind} />}
          {filter.scope === "all" && <input type="hidden" name="scope" value="all" />}
          <input type="search" name="q" defaultValue={filter.q} placeholder="Search headlines" aria-label="Search headlines" />
        </form>
      </div>
      <div className="panel">
        {items.length === 0 ? (
          <p className="empty">No articles match.</p>
        ) : (
          <ul className="feed">
            {items.map((a) => (
              <li key={a.id}>
                <time dateTime={a.published_at}>{when(a.published_at)}</time>
                <div>
                  <a className="t" href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                  {(a.ai_summary ?? a.excerpt) && <p className="s">{a.ai_summary ?? a.excerpt}</p>}
                  <div className="m chips">
                    <span className={`src${a.is_press_release ? " pr" : ""}`}>
                      {a.is_press_release ? "Press release" : "News"} · {a.source}
                    </span>
                    {a.event_type && <span className="chip ev">{humanize(a.event_type)}</span>}
                    {a.basis && <span className="chip">{BASIS_LABEL[a.basis] ?? a.basis}</span>}
                    {a.sentiment !== null && Math.abs(a.sentiment) >= 0.15 && (
                      <span className={`chip ${a.sentiment > 0 ? "pos" : "neg"}`}>
                        {a.sentiment > 0 ? "Positive" : "Negative"}
                      </span>
                    )}
                    {a.companies.map((c) => (
                      <Link key={c.key} className="chip" href={`/stock/${encodeURIComponent(c.key)}`}>
                        {c.name}
                      </Link>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {rows.length > NEWS_PAGE && (
          <div className="pager">
            <Link href={href({ ...base, before: makeCursor(items[items.length - 1].published_at, items[items.length - 1].id) })}>
              Older →
            </Link>
          </div>
        )}
      </div>
    </>
  );
}
