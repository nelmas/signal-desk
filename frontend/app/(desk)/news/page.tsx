import type { Metadata } from "next";
import Link from "next/link";
import { eventLabel, when } from "@/lib/format";
import { getDict } from "@/lib/lang";
import { makeCursor } from "@/lib/paging";
import { getNews, NEWS_PAGE, type NewsFilter } from "@/lib/queries";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDict()).t.nav.news };
}

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
  const [rows, { lang, t }] = await Promise.all([getNews(filter), getDict()]);
  const n = t.news;
  const items = rows.slice(0, NEWS_PAGE);
  const base = { kind: filter.kind, scope: filter.scope === "all" ? "all" : undefined, q: filter.q };
  const last = items[items.length - 1];

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">{n.eyebrow}</span>
        <h1>{n.title}</h1>
        <p>{n.intro}</p>
      </div>
      <div className="filters" role="group">
        {(
          [
            ["all", n.all],
            ["pr", n.pr],
            ["news", n.news],
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
          {n.allArticles}
        </Link>
        <form action="/news">
          {filter.kind !== "all" && <input type="hidden" name="kind" value={filter.kind} />}
          {filter.scope === "all" && <input type="hidden" name="scope" value="all" />}
          <input type="search" name="q" defaultValue={filter.q} placeholder={n.search} aria-label={n.search} />
        </form>
      </div>
      <div className="panel">
        {items.length === 0 ? (
          <p className="empty">{n.empty}</p>
        ) : (
          <ul className="feed">
            {items.map((a) => (
              <li key={a.id}>
                <time dateTime={a.published_at}>{when(a.published_at, lang)}</time>
                <div>
                  <a className="t" href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                  {(a.ai_summary ?? a.excerpt) && <p className="s">{a.ai_summary ?? a.excerpt}</p>}
                  <div className="m chips">
                    <span className={`src${a.is_press_release ? " pr" : ""}`}>
                      {a.is_press_release ? n.pressRelease : n.newsItem} · {a.source}
                    </span>
                    {a.event_type && <span className="chip ev">{eventLabel(a.event_type, lang)}</span>}
                    {a.basis && (
                      <span className="chip">{t.basis[a.basis as keyof typeof t.basis] ?? a.basis}</span>
                    )}
                    {a.sentiment !== null && Math.abs(a.sentiment) >= 0.15 && (
                      <span className={`chip ${a.sentiment > 0 ? "pos" : "neg"}`}>
                        {a.sentiment > 0 ? n.positive : n.negative}
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
        {rows.length > NEWS_PAGE && last && (
          <div className="pager">
            <Link href={href({ ...base, before: makeCursor(last.published_at, last.id) })}>{n.older}</Link>
          </div>
        )}
      </div>
    </>
  );
}
