// Shapes of what the backend stores (see backend/app/models.py and app/briefing).

export type Cited = { text: string; cites: number[] };

export type BriefingContent = {
  disclaimer: string;
  overview: Cited;
  holdings: { company: string; name: string; share: string | null; text: string; cites: number[] }[];
  holdings_also?: string[];
  stories: {
    story_id?: number;
    company: string;
    name: string;
    event_type: string;
    headline: string;
    what_happened: Cited;
    what_it_means: Cited;
    what_next: Cited;
  }[];
  sectors: { name: string; direction: "up" | "down" | "mixed"; reason: string; cites: number[] }[];
  ideas: {
    idea_id?: number;
    company: string;
    name: string;
    market: string;
    market_label?: string;
    why_rise: Cited;
    risks: Cited;
    confidence: "low" | "medium" | "high";
  }[];
  sources: {
    n: number;
    article_id: number;
    title: string;
    url: string;
    source: string;
    published_at: string;
  }[];
  window?: { since: string; until: string };
  checks?: { dropped: string[] };
};

export type Briefing = {
  id: number;
  date: string;
  model: string | null;
  created_at: string;
  content: BriefingContent | null;
};

export type Factor = { score: number; [detail: string]: number | string | null };

export type ScoreComponents = {
  factors: {
    news_volume?: Factor & { articles_24h?: number; usual_per_day?: number };
    event_importance?: Factor;
    sentiment_shift?: Factor & { tone_24h?: number; usual_tone?: number };
  };
  weights_used?: Record<string, number>;
  market?: {
    label: string;
    return_pct?: number;
    typical_move_pct?: number;
    volume_ratio?: number | null;
  };
};

export type ScoreRow = {
  key: string;
  name: string;
  sector: string | null;
  symbol: string | null;
  score: number;
  components: ScoreComponents;
  watched: boolean;
  holding: boolean;
  note: string | null;
};

export type NewsItem = {
  id: number;
  title: string;
  url: string;
  excerpt: string | null;
  is_press_release: boolean;
  published_at: string;
  source: string;
  event_type: string | null;
  basis: string | null;
  sentiment: number | null;
  ai_summary: string | null;
  tag_status: string;
  companies: { key: string; name: string; role: string }[];
};

export type Company = {
  id: number;
  key: string;
  name: string;
  sector: string | null;
  country: string;
  origin: string;
  symbol: string | null;
  mic: string | null;
  currency: string | null;
  watched: boolean;
  holding: boolean;
  note: string | null;
};

export type PricePoint = { date: string; close: number; volume: number | null };
export type CoveragePoint = { day: string; articles: number };
