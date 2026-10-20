import { describe, expect, it } from "vitest";
import { money, radarSummary, sinceEntry } from "./radar";

describe("radar texts", () => {
  it("rounds amounts to sizes in both currencies", () => {
    expect(money(6_664_686, "USD", "en")).toBe("$6.7M");
    expect(money(250_000, "USD", "en")).toBe("$250k");
    expect(money(5_280_318, "SEK", "sv")).toBe("5,3 MSEK");
    expect(money(812_400, "SEK", "sv")).toBe("812 tkr");
  });

  it("explains each signal", () => {
    const quiet = radarSummary("quiet_good_news", { score: 50, move_pct: 1.78, typical_move_pct: 1.87 }, "sv");
    expect(quiet).toContain("signalpoäng 50");
    expect(quiet).toContain("+1,8 %");
    const one = radarSummary("insider_buying", {
      buyers: [{ name: "Jensen", role: "CEO", value: 300_000, currency: "USD", article_ids: [1] }],
      total: 300_000, currency: "USD",
    }, "en");
    expect(one).toBe("Jensen (CEO) bought shares for $300k with their own money.");
    const many = radarSummary("insider_buying", { buyers: [{}, {}, {}] as never, total: 5_280_318, currency: "SEK" }, "sv");
    expect(many).toBe("3 insiders köpte aktier för totalt 5,3 MSEK under 30 dagar.");
    expect(radarSummary(null, {}, "en")).toBe("");
  });

  it("measures the move since entry", () => {
    expect(sinceEntry(100, 103)).toBeCloseTo(3);
    expect(sinceEntry(null, 103)).toBeNull();
    expect(sinceEntry(100, null)).toBeNull();
  });
});
