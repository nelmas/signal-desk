import { describe, expect, it } from "vitest";
import { buildChartDays, countAxis, lastDays, priceDomain, ticks } from "./chart";

describe("chart data", () => {
  it("lines prices and coverage up by calendar day", () => {
    const days = lastDays("2026-10-15", 4);
    expect(days).toEqual(["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"]);
    const rows = buildChartDays(
      days,
      [{ date: "2026-10-13", close: 101, volume: 1 }],
      [{ day: "2026-10-15", articles: 7 }],
    );
    expect(rows).toEqual([
      { day: "2026-10-12", close: null, articles: 0 },
      { day: "2026-10-13", close: 101, articles: 0 },
      { day: "2026-10-14", close: null, articles: 0 },
      { day: "2026-10-15", close: null, articles: 7 },
    ]);
  });

  it("gives round axis bounds that contain every value", () => {
    const [lo, hi] = priceDomain([268.4, 284.6]);
    expect(lo).toBeLessThanOrEqual(268.4);
    expect(hi).toBeGreaterThanOrEqual(284.6);
    expect(ticks([lo, hi]).every((t) => t >= lo && t <= hi)).toBe(true);
    expect(priceDomain([100, 100])[0]).toBeLessThan(100); // flat line still gets a range
  });
});

describe("count axis", () => {
  it("always reaches the largest value, so bars never overflow", () => {
    expect(countAxis(25)).toEqual({ top: 30, ticks: [0, 10, 20, 30] });
    expect(countAxis(0)).toEqual({ top: 1, ticks: [0, 1] });
    for (const max of [1, 3, 7, 9, 23, 48, 151]) {
      const { top, ticks: t } = countAxis(max);
      expect(top).toBeGreaterThanOrEqual(max);
      expect(t.at(-1)).toBe(top);
    }
  });
});
