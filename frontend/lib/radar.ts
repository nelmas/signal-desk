// The Radar's evidence, as the backend stores it (ideas.details), turned into text in
// the reader's language. Pure functions, shared by the Radar page and Facit.

import { num, signed } from "@/lib/format";
import type { Lang } from "@/lib/i18n";

export const SIGNALS = ["quiet_good_news", "insider_buying"] as const;
export type Signal = (typeof SIGNALS)[number];

export type Buyer = { name: string; role: string; value: number; currency: string; article_ids: number[] };
export type RadarDetails = {
  // quiet_good_news
  score?: number;
  tone?: number;
  move_pct?: number;
  typical_move_pct?: number;
  // insider_buying
  buyers?: Buyer[];
  total?: number;
  currency?: string;
  // both: the sources behind the hit
  article_ids?: number[];
};

/** "$1.2M", "$250k"; "5,3 MSEK", "812 tkr". Rounded: these are sizes, not accounts. */
export function money(value: number, currency: string, lang: Lang): string {
  if (currency === "SEK") {
    return value >= 1e6 ? `${num(value / 1e6, 1, lang)} MSEK` : `${num(value / 1000, 0, lang)} tkr`;
  }
  const amount = value >= 1e6 ? `${num(value / 1e6, 1, lang)}M` : `${num(value / 1000, 0, lang)}k`;
  return lang === "sv" ? `${amount} ${currency}` : currency === "USD" ? `$${amount}` : `${amount} ${currency}`;
}

/** One-line reason for a Radar hit, e.g. in Facit's list. */
export function radarSummary(signal: string | null, d: RadarDetails, lang: Lang): string {
  const sv = lang === "sv";
  if (signal === "quiet_good_news") {
    const move = d.move_pct ?? 0;
    const typical = d.typical_move_pct ?? 0;
    return sv
      ? `Starka positiva nyheter (signalpoäng ${num(d.score ?? 0, 0, lang)}) men kursen rörde sig bara ${signed(move, 1, lang)} % senaste handelsdagen; en normal dag rör den sig cirka ${num(typical, 1, lang)} %.`
      : `Strong positive news (signal score ${num(d.score ?? 0, 0, lang)}) but the price moved only ${signed(move, 1, lang)}% on the last trading day; a normal day moves about ${num(typical, 1, lang)}%.`;
  }
  if (signal === "insider_buying") {
    const n = d.buyers?.length ?? 0;
    const total = money(d.total ?? 0, d.currency ?? "USD", lang);
    if (n === 1) {
      const b = d.buyers![0];
      return sv
        ? `${b.name} (${b.role}) köpte aktier för ${total} med egna pengar.`
        : `${b.name} (${b.role}) bought shares for ${total} with their own money.`;
    }
    return sv
      ? `${n} insiders köpte aktier för totalt ${total} under 30 dagar.`
      : `${n} insiders bought shares for ${total} in total within 30 days.`;
  }
  return "";
}

/** Price change since entry, in percent; null before entry or without a newer close. */
export function sinceEntry(entryPrice: number | null, lastClose: number | null): number | null {
  if (!entryPrice || lastClose === null) return null;
  return (lastClose / entryPrice - 1) * 100;
}
