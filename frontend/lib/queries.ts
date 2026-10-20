// Every read the web app makes. Each one checks the session first, so data can't be
// read without logging in even if a page or route were missed by the proxy.

import "server-only";
import { db } from "@/lib/db";
import { parseCursor } from "@/lib/paging";
import { requireSession } from "@/lib/session";
import type { RecordIdea } from "@/lib/record";
import type {
  Briefing,
  Company,
  CoveragePoint,
  NewsItem,
  PricePoint,
  ScoreComponents,
  ScoreRow,
} from "@/lib/types";

const TOPIC = "stocks";
// ISO timestamps from SQL, so the browser's time zone can't shift them.
const ISO = `'YYYY-MM-DD"T"HH24:MI:SS"Z"'`;

/** The newest briefing (or the one for `date`), in `lang` when that day has one. */
export async function getBriefing(date: string | undefined, lang: string): Promise<Briefing | null> {
  await requireSession();
  const rows = await db().query(
    `select id, date::text as date, model, content,
            to_char(created_at at time zone 'UTC', ${ISO}) as created_at
     from briefings
     where topic = $1 and ($2::date is null or date = $2::date)
     order by date desc, (language = $3) desc, created_at desc limit 1`,
    [TOPIC, date ?? null, lang],
  );
  return (rows[0] as Briefing | undefined) ?? null;
}

export async function getBriefingDates(limit = 30): Promise<string[]> {
  await requireSession();
  const rows = await db().query(
    // One entry per day, also when a day has briefings in two languages.
    `select distinct date::text as date from briefings where topic = $1
     order by date desc limit $2`,
    [TOPIC, limit],
  );
  return rows.map((r) => r.date as string);
}

export async function getScores(limit = 40): Promise<{ date: string | null; rows: ScoreRow[] }> {
  await requireSession();
  const rows = await db().query(
    `with d as (select max(date) as date from signal_scores)
     select c.key, c.name, c.sector, l.symbol, s.score::float8 as score, s.components,
            t.company_id is not null as watched, coalesce(t.is_holding, false) as holding,
            t.note, d.date::text as date
     from signal_scores s
     join d on s.date = d.date
     join companies c on c.id = s.company_id
     left join listings l on l.company_id = c.id and l.is_primary
     left join tracked_stocks t on t.company_id = c.id
     where c.topic = $1
     order by s.score desc
     limit $2`,
    [TOPIC, limit],
  );
  return { date: (rows[0]?.date as string) ?? null, rows: rows as ScoreRow[] };
}

export type NewsFilter = {
  kind: "all" | "pr" | "news";
  scope: "tagged" | "all";
  q: string;
  /** Cursor: the last row of the previous page, as "<ISO time>~<article id>". */
  before: string | null;
};


export const NEWS_PAGE = 50;

export async function getNews(f: NewsFilter): Promise<NewsItem[]> {
  await requireSession();
  const cursor = parseCursor(f.before);
  const rows = await db().query(
    `select a.id, a.title, a.url, a.summary as excerpt, a.is_press_release, a.tag_status,
            to_char(a.published_at at time zone 'UTC', ${ISO}) as published_at,
            coalesce(a.raw->>'outlet', s.name) as source,
            an.event_type, an.basis, an.sentiment::float8 as sentiment, an.summary as ai_summary,
            coalesce((select json_agg(json_build_object('key', c.key, 'name', c.name,
                                                        'role', ac.role) order by ac.role desc)
                      from article_companies ac join companies c on c.id = ac.company_id
                      where ac.article_id = a.id), '[]'::json) as companies
     from articles a
     join sources s on s.id = a.source_id
     left join article_analyses an on an.article_id = a.id
     where a.topic = $1
       and ($2 = 'all' or a.is_press_release = ($2 = 'pr'))
       and ($3 = 'all' or a.tag_status = 'tagged')
       and ($4 = '' or a.title ilike '%' || $4 || '%')
       and ($5::timestamptz is null or (a.published_at, a.id) < ($5::timestamptz, $6::int))
     order by a.published_at desc, a.id desc
     limit $7`,
    [TOPIC, f.kind, f.scope, f.q, cursor?.[0] ?? null, cursor?.[1] ?? 0, NEWS_PAGE + 1],
  );
  return rows as NewsItem[];
}

export async function getCompany(key: string): Promise<Company | null> {
  await requireSession();
  const rows = await db().query(
    `select c.id, c.key, c.name, c.sector, c.country, c.origin,
            l.symbol, l.mic, l.currency,
            t.company_id is not null as watched, coalesce(t.is_holding, false) as holding, t.note
     from companies c
     left join listings l on l.company_id = c.id and l.is_primary
     left join tracked_stocks t on t.company_id = c.id
     where c.topic = $1 and c.key = $2`,
    [TOPIC, key],
  );
  return (rows[0] as Company | undefined) ?? null;
}

export async function getStockDetail(companyId: number) {
  await requireSession();
  const [prices, coverage, score, articles] = await Promise.all([
    db().query(
      `select p.date::text as date, p.close::float8 as close, p.volume::float8 as volume
       from prices_daily p join listings l on l.id = p.listing_id
       where l.company_id = $1 and l.is_primary and p.date >= current_date - 70
       order by p.date`,
      [companyId],
    ),
    db().query(
      `select (a.published_at at time zone 'Europe/Stockholm')::date::text as day,
              count(*)::int as articles
       from article_companies ac join articles a on a.id = ac.article_id
       where ac.company_id = $1 and a.published_at >= now() - interval '60 days'
       group by 1 order by 1`,
      [companyId],
    ),
    db().query(
      `select date::text as date, score::float8 as score, components
       from signal_scores where company_id = $1 order by date desc limit 1`,
      [companyId],
    ),
    db().query(
      `select a.id, a.title, a.url, a.summary as excerpt, a.is_press_release, a.tag_status,
              to_char(a.published_at at time zone 'UTC', ${ISO}) as published_at,
              coalesce(a.raw->>'outlet', s.name) as source,
              an.event_type, an.basis, an.sentiment::float8 as sentiment,
              an.importance::float8 as importance, an.summary as ai_summary,
              ac.role, ac.sentiment::float8 as company_sentiment, '[]'::json as companies
       from article_companies ac
       join articles a on a.id = ac.article_id
       join sources s on s.id = a.source_id
       join article_analyses an on an.article_id = a.id
       where ac.company_id = $1 and a.published_at >= now() - interval '30 days'
       order by a.published_at desc limit 40`,
      [companyId],
    ),
  ]);
  return {
    prices: prices as PricePoint[],
    coverage: coverage as CoveragePoint[],
    score: (score[0] as { date: string; score: number; components: ScoreComponents }) ?? null,
    articles: articles as (NewsItem & { importance: number; role: string })[],
  };
}

export async function getTrackRecord(limit = 300): Promise<RecordIdea[]> {
  await requireSession();
  const rows = await db().query(
    // A company suggested twice on one day (e.g. the briefing rewritten in another
    // language) counts once: the first suggestion, so nothing is double counted.
    // Your own picks have no briefing; their day is the day you added them.
    `with dated as (
       select i.*, coalesce(b.date, (i.published_at at time zone 'Europe/Stockholm')::date)
                     as briefing_date
       from ideas i left join briefings b on b.id = i.briefing_id
     ), first as (
       select distinct on (origin, company_id, briefing_date) *
       from dated
       order by origin, company_id, briefing_date, published_at, id
     )
     select i.id, i.origin, c.key, c.name, i.confidence, i.thesis, i.benchmark,
            i.briefing_date::text as briefing_date, i.entry_date::text as entry_date,
            coalesce((select json_object_agg(o.horizon_days, json_build_object(
                        'ret', o.return_pct::float8,
                        'bench', o.benchmark_return_pct::float8,
                        'excess', o.excess_return_pct::float8))
                      from idea_outcomes o where o.idea_id = i.id), '{}'::json) as outcomes
     from first i
     join companies c on c.id = i.company_id
     order by i.published_at desc, i.id desc
     limit $1`,
    [limit],
  );
  return rows as RecordIdea[];
}
