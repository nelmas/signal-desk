// Your own picks in Facit. They are rows in `ideas` with origin 'user', scored by the same
// job and rules as the app's ideas. The web role may insert them and delete them, and only
// these: a pick can be undone until it has entered (its entry price is set).

import "server-only";
import { db } from "@/lib/db";
import { requireSession } from "@/lib/session";

// The market's index, as the briefing job writes it (topics/stocks/topic.yaml).
const BENCHMARK_BY_MIC: Record<string, string> = {
  XSTO: "OMXS30", FNSE: "OMXS30", XSAT: "OMXS30", XNGM: "OMXS30",
  XNAS: "S&P 500", XNYS: "S&P 500",
};

export type Pick = { id: number; thesis: string; added: string; entry_date: string | null; entry_price: number | null };

/** Your latest pick of this company, if any. */
export async function getPick(companyId: number): Promise<Pick | null> {
  await requireSession();
  const rows = await db().query(
    `select id, thesis, (published_at at time zone 'Europe/Stockholm')::date::text as added,
            entry_date::text as entry_date, entry_price::float8 as entry_price
     from ideas where origin = 'user' and company_id = $1
     order by published_at desc, id desc limit 1`,
    [companyId],
  );
  return (rows[0] as Pick | undefined) ?? null;
}

/** Returns an error key, or null when the pick was added. */
export async function addPick(companyId: number, reason: string): Promise<string | null> {
  await requireSession();
  const listing = await db().query(
    `select id, mic from listings where company_id = $1 and is_primary limit 1`,
    [companyId],
  );
  const benchmark = listing[0] ? BENCHMARK_BY_MIC[listing[0].mic as string] : undefined;
  if (!benchmark) return "company";
  // One pick per company and day, the same rule Facit uses for the app's ideas.
  const added = await db().query(
    `insert into ideas (origin, company_id, listing_id, thesis, benchmark, published_at)
     select 'user', $1, $2, $3, $4, now()
     where not exists (
       select 1 from ideas where origin = 'user' and company_id = $1
         and (published_at at time zone 'Europe/Stockholm')::date
           = (now() at time zone 'Europe/Stockholm')::date)
     returning id`,
    [companyId, listing[0].id, reason, benchmark],
  );
  return added.length ? null : "duplicate";
}

/** Undo a pick that hasn't entered yet. Returns an error key, or null when removed. */
export async function removePick(id: number): Promise<string | null> {
  await requireSession();
  const removed = await db().query(
    `delete from ideas where id = $1 and origin = 'user' and entry_date is null returning id`,
    [id],
  );
  return removed.length ? null : "started";
}
