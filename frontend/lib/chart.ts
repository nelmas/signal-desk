// Price-and-coverage chart data: one row per calendar day, so both panels share the axis.

import type { CoveragePoint, PricePoint } from "@/lib/types";

export type ChartDay = { day: string; close: number | null; articles: number };

export function lastDays(today: string, count: number): string[] {
  const end = new Date(`${today}T00:00:00Z`).getTime();
  return Array.from({ length: count }, (_, i) =>
    new Date(end - (count - 1 - i) * 86_400_000).toISOString().slice(0, 10),
  );
}

export function buildChartDays(
  days: string[],
  prices: PricePoint[],
  coverage: CoveragePoint[],
): ChartDay[] {
  const close = new Map(prices.map((p) => [p.date, p.close]));
  const count = new Map(coverage.map((c) => [c.day, c.articles]));
  return days.map((day) => ({ day, close: close.get(day) ?? null, articles: count.get(day) ?? 0 }));
}

/** Rounded axis bounds with a little headroom, e.g. 268.4–284.6 -> 265–290. */
export function priceDomain(values: number[]): [number, number] {
  if (!values.length) return [0, 1];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.abs(hi) * 0.02 || 1;
  const step = niceStep(span / 4);
  return [Math.floor((lo - span * 0.05) / step) * step, Math.ceil((hi + span * 0.05) / step) * step];
}

export function niceStep(raw: number): number {
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * power;
}

export function ticks([lo, hi]: [number, number]): number[] {
  const step = niceStep((hi - lo) / 4);
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/** Axis for counts from 0: the top tick is always at or above the largest value. */
export function countAxis(max: number): { top: number; ticks: number[] } {
  const step = niceStep(Math.max(max, 4) / 4);
  const top = Math.ceil(Math.max(max, 1) / step) * step;
  return { top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) };
}
