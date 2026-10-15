// The stock page's "Why it's on the list": assembled from the score's stored inputs and
// the tagged articles, with numbered sources. Code, not AI, so it can't make anything up.

import { BASIS_LABEL, humanize, MARKET_LABEL, signed, toneWord } from "@/lib/format";
import type { ScoreComponents } from "@/lib/types";

export type ExplainArticle = {
  id: number;
  title: string;
  url: string;
  source: string;
  published_at: string;
  event_type: string | null;
  basis: string | null;
  importance: number;
  ai_summary: string | null;
};

export type Explanation = {
  sentences: { text: string; cites: number[] }[];
  sources: (ExplainArticle & { n: number })[];
};

const BASIS_TRUST: Record<string, number> = { announced: 1, reported: 0.6, commentary: 0.25 };

export function explainScore(
  name: string,
  components: ScoreComponents | null,
  articles: ExplainArticle[],
  since: Date,
): Explanation {
  const recent = articles.filter((a) => new Date(a.published_at) >= since);
  const f = components?.factors ?? {};
  const sources: Explanation["sources"] = [];
  const cite = (a: ExplainArticle): number => {
    const found = sources.find((s) => s.id === a.id);
    if (found) return found.n;
    sources.push({ ...a, n: sources.length + 1 });
    return sources.length;
  };
  const sentences: Explanation["sentences"] = [];

  const count = f.news_volume?.articles_24h ?? recent.length;
  const usual = f.news_volume?.usual_per_day;
  if (count === 0) {
    sentences.push({ text: `${name} had no tagged news in the last 24 hours.`, cites: [] });
    return { sentences, sources };
  }
  sentences.push({
    text:
      usual !== undefined
        ? `${name} had ${count} article${count === 1 ? "" : "s"} in the last 24 hours, against a usual ${usual.toFixed(1)} a day.`
        : `${name} had ${count} article${count === 1 ? "" : "s"} in the last 24 hours.`,
    cites: [],
  });

  // The most important, most trusted recent article: what the score's top event was.
  const top = [...recent].sort(
    (a, b) =>
      b.importance * (BASIS_TRUST[b.basis ?? ""] ?? 0.6) -
      a.importance * (BASIS_TRUST[a.basis ?? ""] ?? 0.6),
  )[0];
  if (top) {
    const basis = BASIS_LABEL[top.basis ?? ""]?.toLowerCase() ?? "reported";
    sentences.push({
      text: `The main event was ${humanize(top.event_type).toLowerCase() || "news"} (${basis}): ${top.ai_summary ?? top.title}`,
      cites: [cite(top)],
    });
  }

  const tone = f.sentiment_shift?.tone_24h;
  const usualTone = f.sentiment_shift?.usual_tone;
  if (tone !== undefined) {
    const others = recent.filter((a) => a !== top).slice(0, 3).map(cite);
    sentences.push({
      text:
        usualTone !== undefined && Math.abs(tone - usualTone) >= 0.2
          ? `Coverage was ${toneWord(tone)} (${signed(tone, 2)}), a shift from its usual ${toneWord(usualTone)} tone (${signed(usualTone, 2)}).`
          : `Coverage was ${toneWord(tone)} (${signed(tone, 2)}), in line with its usual tone.`,
      cites: others,
    });
  }

  const m = components?.market;
  if (m && m.label !== "no_price_data" && m.return_pct !== undefined) {
    const vol = m.volume_ratio ? ` on ${m.volume_ratio.toFixed(1)}× normal volume` : "";
    sentences.push({
      text: `${MARKET_LABEL[m.label] ?? humanize(m.label)}: the shares moved ${signed(m.return_pct)}% in the last session${vol}, against a typical daily move of ${m.typical_move_pct?.toFixed(1)}%.`,
      cites: [],
    });
  } else {
    sentences.push({ text: "No price data for this stock yet.", cites: [] });
  }
  return { sentences, sources };
}
