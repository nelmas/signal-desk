// The stock page's "Why it's on the list": assembled from the score's stored inputs and
// the tagged articles, with numbered sources. Code, not AI, so it can't make anything up.

import { eventLabel, num, signed, toneWord } from "@/lib/format";
import { dict, type Lang } from "@/lib/i18n";
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
  lang: Lang = "en",
): Explanation {
  const d = dict(lang);
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
    sentences.push({ text: d.explain.noNews(name), cites: [] });
    return { sentences, sources };
  }
  sentences.push({
    text: d.explain.count(name, count, usual !== undefined ? num(usual, 1, lang) : undefined),
    cites: [],
  });

  // The most important, most trusted recent article: what the score's top event was.
  const top = [...recent].sort(
    (a, b) =>
      b.importance * (BASIS_TRUST[b.basis ?? ""] ?? 0.6) -
      a.importance * (BASIS_TRUST[a.basis ?? ""] ?? 0.6),
  )[0];
  if (top) {
    const basis = (d.basis[(top.basis ?? "reported") as keyof typeof d.basis] ?? d.basis.reported).toLowerCase();
    const event = top.event_type ? eventLabel(top.event_type, lang).toLowerCase() : d.explain.news;
    sentences.push({
      text: d.explain.main(event, basis, top.ai_summary ?? top.title),
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
          ? d.explain.toneShift(toneWord(tone, lang), signed(tone, 2, lang), toneWord(usualTone, lang), signed(usualTone, 2, lang))
          : d.explain.toneSame(toneWord(tone, lang), signed(tone, 2, lang)),
      cites: others,
    });
  }

  const m = components?.market;
  if (m && m.label !== "no_price_data" && m.return_pct !== undefined) {
    const label = d.market[m.label as keyof typeof d.market] ?? m.label;
    sentences.push({
      text: d.explain.market(
        label,
        signed(m.return_pct, 1, lang),
        m.volume_ratio ? num(m.volume_ratio, 1, lang) : null,
        num(m.typical_move_pct ?? 0, 1, lang),
      ),
      cites: [],
    });
  } else {
    sentences.push({ text: d.explain.noPrices, cites: [] });
  }
  return { sentences, sources };
}
