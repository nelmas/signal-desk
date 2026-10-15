// Display helpers. Times are shown in Stockholm time, the app's home market.

import { dict, type Lang } from "@/lib/i18n";

export const TIME_ZONE = "Europe/Stockholm";

const stockholmDay = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE });

function fmt(lang: Lang, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(dict(lang).locale, options);
}

/** "2026-10-15" -> "Thursday 15 October 2026" / "torsdag 15 oktober 2026" (no time zone shift). */
export function longDate(isoDate: string, lang: Lang = "en"): string {
  return fmt(lang, { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${isoDate}T00:00:00Z`))
    .replace(",", "");
}

/** "2026-10-15" -> "15 Oct" / "15 okt." */
export function shortDate(isoDate: string, lang: Lang = "en"): string {
  return fmt(lang, { day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(`${isoDate}T00:00:00Z`),
  );
}

/** Today's news shows the time, older news the date and time. */
export function when(isoTimestamp: string, lang: Lang = "en", now = new Date()): string {
  const t = new Date(isoTimestamp);
  const sameDay = stockholmDay.format(t) === stockholmDay.format(now);
  return fmt(
    lang,
    sameDay
      ? { hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE }
      : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE },
  ).format(t);
}

/** "profit_warning" -> "Profit warning". Fallback for event types without a translation. */
export function humanize(key: string | null | undefined): string {
  if (!key) return "";
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function eventLabel(key: string | null | undefined, lang: Lang = "en"): string {
  return (key && dict(lang).events[key]) || humanize(key);
}

/** Fixed decimals with a real minus sign; Swedish uses a decimal comma. */
export function num(n: number, digits = 1, lang: Lang = "en"): string {
  const text = Math.abs(n).toFixed(digits);
  return `${n < 0 ? "−" : ""}${lang === "sv" ? text.replace(".", ",") : text}`;
}

export function signed(n: number, digits = 1, lang: Lang = "en"): string {
  return `${n > 0 ? "+" : ""}${num(n, digits, lang)}`;
}

export function toneWord(tone: number, lang: Lang = "en"): string {
  const t = dict(lang).tone;
  if (tone >= 0.5) return t.clearlyPositive;
  if (tone >= 0.15) return t.positive;
  if (tone > -0.15) return t.neutral;
  if (tone > -0.5) return t.negative;
  return t.clearlyNegative;
}

/** Briefings written before prompt v2 may contain article ids in the prose ("[1988]"). */
export function stripInlineIds(text: string): string {
  return text.replace(/\s*\[\d+(?:\s*,\s*\d+)*\]/g, "");
}
