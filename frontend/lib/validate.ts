// Validation for the Settings page. Everything a form sends is checked here before it is
// written, so a hand-crafted request can't store anything the jobs don't understand.

export type Weights = { news_volume: number; event_importance: number; sentiment_shift: number };
export const WEIGHT_KEYS = ["news_volume", "event_importance", "sentiment_shift"] as const;

export type BriefingPrefs = {
  send_time: string;
  timezone: string;
  language: "en" | "sv";
  max_stories: number;
  max_sectors: number;
  max_ideas: number;
};

/** `error` is a message key; the Settings page shows it in the user's language. */
export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

type Form = { get(name: string): FormDataEntryValue | null };

function int(form: Form, name: string, min: number, max: number): number | null {
  const raw = String(form.get(name) ?? "").trim();
  if (!/^\d{1,3}$/.test(raw)) return null;
  const n = Number(raw);
  return n >= min && n <= max ? n : null;
}

/** Percentages in, fractions summing to 1 out (what the scoring job reads). */
export function parseWeights(form: Form): Result<Weights> {
  const raw = WEIGHT_KEYS.map((k) => int(form, k, 0, 100));
  if (raw.some((v) => v === null)) return { ok: false, error: "weights_format" };
  const total = (raw as number[]).reduce((a, b) => a + b, 0);
  if (total === 0) return { ok: false, error: "weights_zero" };
  const [a, b, c] = (raw as number[]).map((v) => Math.round((v / total) * 10000) / 10000);
  return { ok: true, value: { news_volume: a, event_importance: b, sentiment_shift: c } };
}

export function parseBriefing(form: Form, current: BriefingPrefs): Result<BriefingPrefs> {
  const sendTime = String(form.get("send_time") ?? "");
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(sendTime)) return { ok: false, error: "send_time" };
  const language = String(form.get("language") ?? "");
  if (language !== "en" && language !== "sv") return { ok: false, error: "language" };
  const stories = int(form, "max_stories", 3, 8);
  const ideas = int(form, "max_ideas", 0, 5);
  if (stories === null) return { ok: false, error: "stories" };
  if (ideas === null) return { ok: false, error: "ideas" };
  return {
    ok: true,
    value: { ...current, send_time: sendTime, language, max_stories: stories, max_ideas: ideas },
  };
}

const EMAIL = /^[^\s@<>()",;]+@[^\s@<>()",;]+\.[a-z]{2,}$/i;

export function parseEmail(form: Form): Result<{ enabled: boolean; to: string | null }> {
  const enabled = form.get("enabled") === "on";
  const to = String(form.get("to") ?? "").trim();
  if (to && (to.length > 200 || !EMAIL.test(to))) return { ok: false, error: "email_format" };
  if (enabled && !to) return { ok: false, error: "email_missing" };
  return { ok: true, value: { enabled, to: to || null } };
}

/** On/off per known key; unknown keys in the form are ignored. */
export function parseToggles(form: Form, keys: string[]): Record<string, boolean> {
  return Object.fromEntries(keys.map((k) => [k, form.get(`on_${k}`) === "on"]));
}

export function parseNote(value: FormDataEntryValue | null): string | null {
  const note = String(value ?? "").trim().slice(0, 200);
  return note || null;
}

/** The reason for one of your own picks (Facit): 3 to 300 characters, spaces tidied. */
export function parseReason(value: FormDataEntryValue | null): Result<string> {
  const reason = String(value ?? "").replace(/\s+/g, " ").trim();
  if (reason.length < 3 || reason.length > 300) return { ok: false, error: "reason" };
  return { ok: true, value: reason };
}
