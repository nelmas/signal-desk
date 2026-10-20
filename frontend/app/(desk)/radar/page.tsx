import type { Metadata } from "next";
import { CompanyLink } from "@/components/bits";
import { signed, shortDate, when } from "@/lib/format";
import type { Dict, Lang } from "@/lib/i18n";
import { getDict } from "@/lib/lang";
import { getRadar, getTrackRecord, type RadarHit, type RadarSource } from "@/lib/queries";
import { money, radarSummary, sinceEntry, SIGNALS, type Signal } from "@/lib/radar";
import { headlineHorizon, horizonStats } from "@/lib/record";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDict()).t.nav.radar };
}

const SECTION: Record<Signal, "quiet" | "insider"> = {
  quiet_good_news: "quiet",
  insider_buying: "insider",
};

export default async function RadarPage() {
  const [{ hits, sources }, record, { lang, t }] = await Promise.all([
    getRadar(),
    getTrackRecord(1000),
    getDict(),
  ]);
  const r = t.radar;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">{r.eyebrow}</span>
        <h1>{r.title}</h1>
        <p>{r.intro}</p>
      </div>

      {SIGNALS.map((signal) => {
        const s = r[SECTION[signal]];
        const scored = record.filter((i) => i.origin === "radar" && i.signal === signal);
        const h = headlineHorizon(scored);
        const stats = h ? horizonStats(scored, h) : null;
        const list = hits.filter((hit) => hit.signal === signal);
        return (
          <section className="panel section" key={signal} id={signal}>
            <header>
              <h2>{s.title}</h2>
              <span className="eyebrow">{list.length}</span>
            </header>
            <p className="help">{s.rule}</p>
            <p className="help">
              {stats && stats.beat !== null
                ? r.record(`${Math.round(stats.beat * 100)} %`, stats.compared, t.record.afterDays(stats.horizon))
                : r.recordNone}
            </p>
            {list.length === 0 ? (
              <p className="empty">{r.none}</p>
            ) : (
              list.map((hit) => <Hit key={hit.id} hit={hit} sources={sources} lang={lang} t={t} />)
            )}
          </section>
        );
      })}

      <p className="disclaimer">{r.disclaimer}</p>
    </>
  );
}

function Hit({ hit, sources, lang, t }: {
  hit: RadarHit;
  sources: Map<number, RadarSource>;
  lang: Lang;
  t: Dict;
}) {
  const r = t.radar;
  const move = sinceEntry(hit.entry_price, hit.last_close);
  // The same press release often arrives from two outlets; list it once.
  const seen = new Set<string>();
  const cited = (hit.details.article_ids ?? []).flatMap((id) => {
    const src = sources.get(id);
    if (!src || seen.has(src.title.toLowerCase())) return [];
    seen.add(src.title.toLowerCase());
    return [src];
  });
  return (
    <div className="idea">
      <div className="name">
        <h3>
          <CompanyLink k={hit.key} name={hit.name} />
        </h3>
        <span className="muted" style={{ fontSize: ".8rem" }}>
          {r.flagged} {shortDate(hit.published_at.slice(0, 10), lang)}
        </span>
        <span style={{ fontSize: ".85rem" }}>
          {!hit.entry_date ? (
            <span className="muted">{r.waiting}</span>
          ) : (
            <>
              {r.sinceEntry}:{" "}
              {move === null ? (
                <span className="muted">{r.noPrice}</span>
              ) : (
                <b className={move >= 0 ? "up" : "down"}>{signed(move, 1, lang)}&nbsp;%</b>
              )}
            </>
          )}
        </span>
      </div>
      <div>
        <p>{radarSummary(hit.signal, hit.details, lang)}</p>
        {hit.signal === "insider_buying" && (hit.details.buyers?.length ?? 0) > 1 && (
          <ul className="buyers">
            {hit.details.buyers!.map((b) => (
              <li key={b.name}>
                {b.name} ({b.role}) {r.bought} {money(b.value, b.currency, lang)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <span className="eyebrow">{r.sources}</span>
        <ol className="sources">
          {cited.map((src) => (
            <li key={src.id}>
              <a href={src.url} target="_blank" rel="noopener noreferrer">
                {src.title}
              </a>{" "}
              · {src.source} · {when(src.published_at, lang)}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
