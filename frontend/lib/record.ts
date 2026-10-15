// Track record statistics, computed from each idea's stored outcomes.

export const HORIZONS = [1, 5, 20] as const;
export type Horizon = (typeof HORIZONS)[number];
/** Below this many scored ideas, a hit rate says little; the page says so. */
export const MIN_SAMPLE = 20;

export type Outcome = { ret: number; bench: number | null; excess: number | null };

export type RecordIdea = {
  id: number;
  key: string;
  name: string;
  confidence: "low" | "medium" | "high";
  thesis: string;
  benchmark: string;
  briefing_date: string;
  entry_date: string | null;
  outcomes: Partial<Record<string, Outcome>>;
};

export type HorizonStats = {
  horizon: Horizon;
  scored: number; // ideas with a result at this horizon
  compared: number; // of those, with an index result to compare with
  beat: number | null; // share that beat the index, 0-1
  avgReturn: number | null;
  avgExcess: number | null;
};

const mean = (xs: number[]): number | null => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

export function horizonStats(ideas: RecordIdea[], horizon: Horizon): HorizonStats {
  const results = ideas.flatMap((i) => (i.outcomes[String(horizon)] ? [i.outcomes[String(horizon)]!] : []));
  const excess = results.flatMap((o) => (o.excess === null ? [] : [o.excess]));
  return {
    horizon,
    scored: results.length,
    compared: excess.length,
    beat: excess.length ? excess.filter((x) => x > 0).length / excess.length : null,
    avgReturn: mean(results.map((o) => o.ret)),
    avgExcess: mean(excess),
  };
}

/** The longest horizon that has any results, for the headline numbers. */
export function headlineHorizon(ideas: RecordIdea[]): Horizon | null {
  return [...HORIZONS].reverse().find((h) => horizonStats(ideas, h).compared > 0) ?? null;
}

export function byConfidence(ideas: RecordIdea[], horizon: Horizon) {
  return (["high", "medium", "low"] as const).map((level) => ({
    level,
    ...horizonStats(ideas.filter((i) => i.confidence === level), horizon),
  }));
}
