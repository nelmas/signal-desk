import { describe, expect, it } from "vitest";
import { byConfidence, headlineHorizon, horizonStats, type RecordIdea } from "./record";

function idea(id: number, confidence: RecordIdea["confidence"], outcomes: RecordIdea["outcomes"]): RecordIdea {
  return {
    id, key: `k${id}`, name: `N${id}`, confidence, thesis: "", benchmark: "S&P 500",
    briefing_date: "2026-10-15", entry_date: "2026-10-15", outcomes,
  };
}

const IDEAS = [
  idea(1, "high", { "1": { ret: 2, bench: 1, excess: 1 }, "5": { ret: 4, bench: 1, excess: 3 } }),
  idea(2, "low", { "1": { ret: -1, bench: 1, excess: -2 }, "5": { ret: 1, bench: 2, excess: -1 } }),
  idea(3, "low", { "1": { ret: 3, bench: null, excess: null } }), // no index data
  idea(4, "medium", {}), // not scored yet
];

describe("track record stats", () => {
  it("counts, hit rate and averages per horizon", () => {
    expect(horizonStats(IDEAS, 1)).toEqual({
      horizon: 1, scored: 3, compared: 2, beat: 0.5, avgReturn: 4 / 3, avgExcess: -0.5,
    });
    expect(horizonStats(IDEAS, 20)).toEqual({
      horizon: 20, scored: 0, compared: 0, beat: null, avgReturn: null, avgExcess: null,
    });
  });

  it("headlines the longest horizon with results", () => {
    expect(headlineHorizon(IDEAS)).toBe(5);
    expect(headlineHorizon([idea(9, "low", {})])).toBeNull();
  });

  it("splits by confidence", () => {
    const rows = byConfidence(IDEAS, 5);
    expect(rows.map((r) => [r.level, r.compared, r.beat])).toEqual([
      ["high", 1, 1],
      ["medium", 0, null],
      ["low", 1, 0],
    ]);
  });
});
