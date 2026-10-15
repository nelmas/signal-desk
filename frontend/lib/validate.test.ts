import { describe, expect, it } from "vitest";
import { parseBriefing, parseEmail, parseNote, parseToggles, parseWeights, type BriefingPrefs } from "./validate";

const form = (entries: Record<string, string>) => {
  const f = new FormData();
  for (const [k, v] of Object.entries(entries)) f.set(k, v);
  return f;
};

const CURRENT: BriefingPrefs = {
  send_time: "07:00", timezone: "Europe/Stockholm", language: "en",
  max_stories: 5, max_sectors: 3, max_ideas: 3,
};

describe("weights", () => {
  it("turns percentages into fractions that sum to 1", () => {
    const r = parseWeights(form({ news_volume: "40", event_importance: "40", sentiment_shift: "20" }));
    expect(r).toEqual({ ok: true, value: { news_volume: 0.4, event_importance: 0.4, sentiment_shift: 0.2 } });
    const odd = parseWeights(form({ news_volume: "1", event_importance: "1", sentiment_shift: "1" }));
    expect(odd.ok && odd.value.news_volume).toBeCloseTo(1 / 3, 3);
  });

  it("rejects nonsense", () => {
    const bads: Record<string, string>[] = [
      { news_volume: "0", event_importance: "0", sentiment_shift: "0" },
      { news_volume: "-5", event_importance: "50", sentiment_shift: "50" },
      { news_volume: "101", event_importance: "0", sentiment_shift: "0" },
      { news_volume: "1e2", event_importance: "0", sentiment_shift: "0" },
      { news_volume: "50", event_importance: "50" },
    ];
    for (const bad of bads) {
      expect(parseWeights(form(bad)).ok).toBe(false);
    }
  });
});

describe("briefing", () => {
  it("keeps settings the form doesn't edit", () => {
    const r = parseBriefing(form({ send_time: "08:30", language: "sv", max_stories: "6", max_ideas: "2" }), CURRENT);
    expect(r).toEqual({
      ok: true,
      value: { ...CURRENT, send_time: "08:30", language: "sv", max_stories: 6, max_ideas: 2 },
    });
  });

  it("rejects bad times, languages and counts", () => {
    const ok = { send_time: "08:30", language: "en", max_stories: "5", max_ideas: "3" };
    expect(parseBriefing(form({ ...ok, send_time: "24:00" }), CURRENT).ok).toBe(false);
    expect(parseBriefing(form({ ...ok, send_time: "8:30" }), CURRENT).ok).toBe(false);
    expect(parseBriefing(form({ ...ok, language: "de" }), CURRENT).ok).toBe(false);
    expect(parseBriefing(form({ ...ok, max_stories: "20" }), CURRENT).ok).toBe(false);
    expect(parseBriefing(form({ ...ok, max_ideas: "-1" }), CURRENT).ok).toBe(false);
  });
});

describe("email", () => {
  it("needs a plausible address when on", () => {
    expect(parseEmail(form({ enabled: "on", to: "me@outlook.com" }))).toEqual({
      ok: true, value: { enabled: true, to: "me@outlook.com" },
    });
    expect(parseEmail(form({ to: "" }))).toEqual({ ok: true, value: { enabled: false, to: null } });
    expect(parseEmail(form({ enabled: "on", to: "" })).ok).toBe(false);
    for (const bad of ["me", "me@x", "a b@x.com", "<me@x.com>", "x@y.com, z@w.com"]) {
      expect(parseEmail(form({ to: bad })).ok).toBe(false);
    }
  });
});

describe("toggles and notes", () => {
  it("only knows the keys it is given", () => {
    expect(parseToggles(form({ on_mfn: "on", on_evil: "on" }), ["mfn", "sec-8k"])).toEqual({
      mfn: true, "sec-8k": false,
    });
  });

  it("trims and limits notes", () => {
    expect(parseNote("  ")).toBeNull();
    expect(parseNote("x".repeat(500))).toHaveLength(200);
  });
});
