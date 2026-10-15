import { describe, expect, it } from "vitest";
import { explainScore, type ExplainArticle } from "./explain";
import { humanize, longDate, signed, stripInlineIds, when } from "./format";

const NOW = new Date("2026-10-15T08:00:00Z");
const SINCE = new Date(NOW.getTime() - 24 * 3600 * 1000);

function article(id: number, hoursAgo: number, extra: Partial<ExplainArticle> = {}): ExplainArticle {
  return {
    id,
    title: `Title ${id}`,
    url: `https://x/${id}`,
    source: "Reuters",
    published_at: new Date(NOW.getTime() - hoursAgo * 3600 * 1000).toISOString(),
    event_type: "contract",
    basis: "reported",
    importance: 0.5,
    ai_summary: `Summary ${id}.`,
    ...extra,
  };
}

describe("explainScore", () => {
  it("leads with the most important trusted article and numbers sources in order", () => {
    const articles = [
      article(1, 2, { importance: 0.9, basis: "commentary" }), // 0.225
      article(2, 3, { importance: 0.8, basis: "announced", event_type: "profit_warning" }), // 0.8
      article(3, 5),
      article(4, 40), // outside the 24 hours
    ];
    const components = {
      factors: {
        news_volume: { score: 80, articles_24h: 3, usual_per_day: 0.5 },
        sentiment_shift: { score: 70, tone_24h: -0.6, usual_tone: 0.1 },
      },
      market: { label: "moving_with_news", return_pct: -4.2, typical_move_pct: 1.1, volume_ratio: 2.4 },
    };
    const e = explainScore("SKF", components, articles, SINCE);
    expect(e.sentences[0].text).toBe(
      "SKF had 3 articles in the last 24 hours, against a usual 0.5 a day.",
    );
    expect(e.sentences[1].text).toBe("The main event was profit warning (announced): Summary 2.");
    expect(e.sentences[1].cites).toEqual([1]);
    expect(e.sources.map((s) => s.id)).toEqual([2, 1, 3]);
    expect(e.sentences[2].text).toContain("a shift from its usual neutral tone (+0.10)");
    expect(e.sentences[3].text).toBe(
      "Moving with the news: the shares moved −4.2% in the last session on 2.4× normal volume, against a typical daily move of 1.1%.",
    );
  });

  it("says plainly when there is no news or no prices", () => {
    expect(explainScore("Volvo", null, [], SINCE).sentences).toEqual([
      { text: "Volvo had no tagged news in the last 24 hours.", cites: [] },
    ]);
    const e = explainScore("Volvo", { factors: {} }, [article(1, 1)], SINCE);
    expect(e.sentences.at(-1)?.text).toBe("No price data for this stock yet.");
  });
});

describe("format", () => {
  it("formats dates without time zone surprises", () => {
    expect(longDate("2026-10-15")).toBe("Thursday 15 October 2026");
    expect(when("2026-10-15T06:30:00Z", "en", NOW)).toBe("08:30"); // same Stockholm day
    expect(when("2026-10-13T06:30:00Z", "en", NOW)).toBe("13 Oct, 08:30");
  });

  it("formats labels and signs", () => {
    expect(humanize("profit_warning")).toBe("Profit warning");
    expect(signed(3.14)).toBe("+3.1");
    expect(signed(-0.5, 2)).toBe("−0.50");
    expect(stripInlineIds("Fabs [1988], while buybacks [12, 13] grew.")).toBe("Fabs, while buybacks grew.");
  });
});

describe("Swedish", () => {
  it("explains and formats in Swedish", () => {
    const components = {
      factors: {
        news_volume: { score: 80, articles_24h: 1, usual_per_day: 0.5 },
        sentiment_shift: { score: 10, tone_24h: 0.2, usual_tone: 0.1 },
      },
      market: { label: "small_move", return_pct: 1.25, typical_move_pct: 1.1, volume_ratio: null },
    };
    const e = explainScore("Volvo", components, [article(1, 2, { basis: "announced" })], SINCE, "sv");
    expect(e.sentences.map((s) => s.text)).toEqual([
      "Volvo hade 1 artikel de senaste 24 timmarna, mot normalt 0,5 per dag.",
      "Den viktigaste händelsen var order/avtal (meddelat): Summary 1.",
      "Tonen var positiv (+0,20), i linje med den vanliga.",
      "Liten rörelse: aktien rörde sig +1,3 % senaste handelsdagen, mot en normal dagsrörelse på 1,1 %.",
    ]);
    expect(longDate("2026-10-15", "sv")).toBe("torsdag 15 oktober 2026");
    expect(when("2026-10-13T06:30:00Z", "sv", NOW)).toMatch(/^13 okt\.? 08:30$/);
  });
});
