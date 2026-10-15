// Display helpers. Times are shown in Stockholm time, the app's home market.

export const TIME_ZONE = "Europe/Stockholm";

const dayFmt = new Intl.DateTimeFormat("en-GB", {
  weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
});
const shortDayFmt = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", timeZone: "UTC",
});
const timeFmt = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE,
});
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE,
});
const stockholmDay = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE });

/** "2026-10-15" -> "Thursday 15 October 2026" (a calendar date, no time zone shift). */
export function longDate(isoDate: string): string {
  return dayFmt.format(new Date(`${isoDate}T00:00:00Z`)).replace(",", "");
}

/** "2026-10-15" -> "15 Oct". */
export function shortDate(isoDate: string): string {
  return shortDayFmt.format(new Date(`${isoDate}T00:00:00Z`));
}

/** Today's news shows the time, older news the date and time. */
export function when(isoTimestamp: string, now = new Date()): string {
  const t = new Date(isoTimestamp);
  return stockholmDay.format(t) === stockholmDay.format(now) ? timeFmt.format(t) : dateTimeFmt.format(t);
}

/** "profit_warning" -> "Profit warning". */
export function humanize(key: string | null | undefined): string {
  if (!key) return "";
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const BASIS_LABEL: Record<string, string> = {
  announced: "Announced",
  reported: "Reported",
  commentary: "Commentary",
};

export const MARKET_LABEL: Record<string, string> = {
  not_priced_in_yet: "No price reaction yet",
  moving_with_news: "Moving with the news",
  moving_against_news: "Moving against the news",
  small_move: "Small move",
  no_price_data: "No price data",
};

export function signed(n: number, digits = 1): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}`;
}

export function toneWord(tone: number): string {
  if (tone >= 0.5) return "clearly positive";
  if (tone >= 0.15) return "positive";
  if (tone > -0.15) return "neutral";
  if (tone > -0.5) return "negative";
  return "clearly negative";
}

/** Briefings written before prompt v2 may contain article ids in the prose ("[1988]"). */
export function stripInlineIds(text: string): string {
  return text.replace(/\s*\[\d+(?:\s*,\s*\d+)*\]/g, "");
}
