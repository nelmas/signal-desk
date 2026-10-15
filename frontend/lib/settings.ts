// Reads and writes for the Settings page. Writes touch only `settings` and
// `tracked_stocks`, the two tables the web app's database role may change.

import "server-only";
import { db } from "@/lib/db";
import { requireSession } from "@/lib/session";
import type { BriefingPrefs, Weights } from "@/lib/validate";

const TOPIC = "stocks";

export type SourceRow = { key: string; name: string; market: string | null; on: boolean };
export type WatchRow = {
  company_id: number;
  key: string;
  name: string;
  symbol: string | null;
  holding: boolean;
  note: string | null;
};
export type CompanyHit = { id: number; key: string; name: string; symbol: string | null; mic: string | null; watched: boolean };

export const BRIEFING_DEFAULTS: BriefingPrefs = {
  send_time: "07:00", timezone: "Europe/Stockholm", language: "en",
  max_stories: 5, max_sectors: 3, max_ideas: 3,
};
export const MARKET_NAMES: Record<string, string> = { SE: "Swedish marketplaces", US: "US exchanges" };

export async function getSettingsData() {
  await requireSession();
  const [rows, sources, watch] = await Promise.all([
    db().query(`select key, value from settings`),
    db().query(
      `select key, name, market from sources where topic = $1 and enabled order by market, name`,
      [TOPIC],
    ),
    db().query(
      `select t.company_id, c.key, c.name, l.symbol, t.is_holding as holding, t.note
       from tracked_stocks t
       join companies c on c.id = t.company_id
       left join listings l on l.company_id = c.id and l.is_primary
       order by t.is_holding desc, c.name`,
    ),
  ]);
  const value = (key: string) =>
    ((rows.find((r) => r.key === key)?.value as Record<string, unknown>) ?? {});
  const sourceOn = value("sources");
  const marketOn = value("markets");
  const markets = [...new Set(sources.map((s) => s.market as string | null).filter(Boolean))] as string[];
  const weights = value("scoring_weights") as Partial<Weights>;
  const email = value("email");
  return {
    weights: {
      news_volume: Number(weights.news_volume ?? 0.4),
      event_importance: Number(weights.event_importance ?? 0.35),
      sentiment_shift: Number(weights.sentiment_shift ?? 0.25),
    },
    briefing: { ...BRIEFING_DEFAULTS, ...(value("briefing") as Partial<BriefingPrefs>) },
    email: { enabled: email.enabled === true, to: typeof email.to === "string" ? email.to : "" },
    sources: sources.map((s) => ({ ...(s as Omit<SourceRow, "on">), on: sourceOn[s.key] !== false })),
    markets: markets.map((m) => ({ key: m, name: MARKET_NAMES[m] ?? m, on: marketOn[m] !== false })),
    watchlist: watch as WatchRow[],
  };
}

export async function searchCompanies(q: string): Promise<CompanyHit[]> {
  await requireSession();
  const term = q.trim().slice(0, 60);
  if (term.length < 2) return [];
  const rows = await db().query(
    `select c.id, c.key, c.name, l.symbol, l.mic,
            exists (select 1 from tracked_stocks t where t.company_id = c.id) as watched
     from companies c
     left join listings l on l.company_id = c.id and l.is_primary
     where c.topic = $1 and c.active
       and (c.name ilike '%' || $2 || '%' or l.symbol ilike $2 || '%')
     order by (l.symbol ilike $2) desc, (c.origin = 'curated') desc, length(c.name)
     limit 12`,
    [TOPIC, term],
  );
  return rows as CompanyHit[];
}

export async function saveSetting(key: string, value: unknown): Promise<void> {
  await requireSession();
  await db().query(
    `insert into settings (key, value, updated_at) values ($1, $2::jsonb, now())
     on conflict (key) do update set value = excluded.value, updated_at = now()`,
    [key, JSON.stringify(value)],
  );
}

export async function watchCompany(companyId: number, holding: boolean): Promise<void> {
  await requireSession();
  await db().query(
    `insert into tracked_stocks (company_id, is_holding)
     select id, $2 from companies where id = $1 and topic = $3
     on conflict (company_id) do update set is_holding = tracked_stocks.is_holding or $2`,
    [companyId, holding, TOPIC],
  );
}

export async function updateWatch(companyId: number, holding: boolean, note: string | null): Promise<void> {
  await requireSession();
  await db().query(`update tracked_stocks set is_holding = $2, note = $3 where company_id = $1`, [
    companyId, holding, note,
  ]);
}

export async function unwatch(companyId: number): Promise<void> {
  await requireSession();
  await db().query(`delete from tracked_stocks where company_id = $1`, [companyId]);
}
