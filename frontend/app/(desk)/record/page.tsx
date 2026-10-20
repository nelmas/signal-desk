import type { Metadata } from "next";
import { CompanyLink } from "@/components/bits";
import { removeMyPick } from "@/app/(desk)/stock/[key]/actions";
import { shortDate, signed } from "@/lib/format";
import type { Lang } from "@/lib/i18n";
import { getDict } from "@/lib/lang";
import { getTrackRecord } from "@/lib/queries";
import {
  byConfidence,
  headlineHorizon,
  HORIZONS,
  horizonStats,
  MIN_SAMPLE,
  type Outcome,
} from "@/lib/record";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDict()).t.nav.record };
}

function pct(x: number | null, lang: Lang): string {
  return x === null ? "–" : `${signed(x, 1, lang)} %`;
}

function share(x: number | null): string {
  return x === null ? "–" : `${Math.round(x * 100)} %`;
}

function Result({ o, lang, vs }: { o: Outcome | undefined; lang: Lang; vs: (x: string) => string }) {
  if (!o) return null;
  return (
    <span title={o.excess !== null ? vs(pct(o.excess, lang)) : undefined}>
      <span className={o.ret >= 0 ? "up" : "down"}>{pct(o.ret, lang)}</span>
      {o.excess !== null && (
        <span className="muted" style={{ display: "block", fontSize: ".75rem" }}>
          {vs(pct(o.excess, lang))}
        </span>
      )}
    </span>
  );
}

type Props = { searchParams: Promise<{ pick?: string; pick_error?: string }> };

export default async function RecordPage({ searchParams }: Props) {
  const [all, { lang, t }, { pick, pick_error }] = await Promise.all([
    getTrackRecord(),
    getDict(),
    searchParams,
  ]);
  const r = t.record;
  // The headline numbers answer "is the agent any good?"; your picks get their own row below.
  const ideas = all.filter((i) => i.origin === "agent");
  const mine = all.filter((i) => i.origin === "user");
  const head = headlineHorizon(ideas);
  const headStats = head ? horizonStats(ideas, head) : null;
  const oldest = ideas.at(-1)?.briefing_date;
  const compareAt = head ?? headlineHorizon(mine) ?? 1;
  const pickNote = pick === "removed" ? t.pick.removed : undefined;
  const pickError = pick_error ? t.pick.errors[pick_error] : undefined;

  return (
    <>
      <div className="view-head">
        <span className="eyebrow">{r.eyebrow}</span>
        <h1>{r.title}</h1>
        <p>{r.intro}</p>
      </div>

      {pickNote && <p className="notice" role="status" id="pick">{pickNote}</p>}
      {pickError && <p className="error" role="alert" id="pick">{pickError}</p>}

      {all.length === 0 ? (
        <p className="empty">{r.empty}</p>
      ) : (
        <>
          <div className="tiles">
            <div className="panel tile">
              <span className="eyebrow">{r.logged}</span>
              <span className="v">{ideas.length}</span>
              {oldest && <span className="d">{r.since(shortDate(oldest, lang))}</span>}
            </div>
            <div className="panel tile">
              <span className="eyebrow">{r.beat}</span>
              <span className="v">{headStats ? share(headStats.beat) : "–"}</span>
              {headStats && (
                <span className="d">
                  {r.afterDays(headStats.horizon)}, {r.ofCompared(headStats.compared)}
                </span>
              )}
            </div>
            <div className="panel tile">
              <span className="eyebrow">{r.avgExcess}</span>
              <span className={`v ${headStats?.avgExcess != null ? (headStats.avgExcess >= 0 ? "up" : "down") : ""}`}>
                {headStats ? pct(headStats.avgExcess, lang) : "–"}
              </span>
              {headStats && <span className="d">{r.afterDays(headStats.horizon)}</span>}
            </div>
          </div>

          {!headStats ? (
            <p className="notice">{r.noneYet}</p>
          ) : (
            headStats.compared < MIN_SAMPLE && (
              <p className="notice">{r.tooFew(headStats.compared, MIN_SAMPLE)}</p>
            )
          )}

          {headStats && (
            <div className="split">
              <section className="panel section tbl-wrap">
                <header><h2>{r.byHorizon}</h2></header>
                <table>
                  <thead>
                    <tr>
                      <th>{r.held}</th>
                      <th className="num">{r.scored}</th>
                      <th className="num">{r.beat}</th>
                      <th className="num">{r.avgReturn}</th>
                      <th className="num">{r.avgExcess}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {HORIZONS.map((h) => {
                      const s = horizonStats(ideas, h);
                      return (
                        <tr key={h}>
                          <td>{r.days(h)}</td>
                          <td className="num mono">{s.scored}</td>
                          <td className="num mono">{share(s.beat)}</td>
                          <td className="num mono">{pct(s.avgReturn, lang)}</td>
                          <td className="num mono">{pct(s.avgExcess, lang)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
              <section className="panel section tbl-wrap">
                <header>
                  <h2>{r.byConfidence}</h2>
                  <span className="eyebrow">{r.afterDays(headStats.horizon)}</span>
                </header>
                <table>
                  <thead>
                    <tr>
                      <th>{r.cols.confidence}</th>
                      <th className="num">{r.scored}</th>
                      <th className="num">{r.beat}</th>
                      <th className="num">{r.avgExcess}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byConfidence(ideas, headStats.horizon).map((row) => (
                      <tr key={row.level}>
                        <td>{t.confidence[row.level]}</td>
                        <td className="num mono">{row.compared}</td>
                        <td className="num mono">{share(row.beat)}</td>
                        <td className="num mono">{pct(row.avgExcess, lang)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          )}

          {mine.length > 0 && (
            <section className="panel section tbl-wrap">
              <header>
                <h2>
                  {r.agent} · {r.mine}
                </h2>
                <span className="eyebrow">{r.afterDays(compareAt)}</span>
              </header>
              <table>
                <thead>
                  <tr>
                    <th>{r.byWho}</th>
                    <th className="num">{r.logged}</th>
                    <th className="num">{r.scored}</th>
                    <th className="num">{r.beat}</th>
                    <th className="num">{r.avgReturn}</th>
                    <th className="num">{r.avgExcess}</th>
                  </tr>
                </thead>
                <tbody>
                  {([[r.agent, ideas], [r.mine, mine]] as const).map(([label, group]) => {
                    const s = horizonStats(group, compareAt);
                    return (
                      <tr key={label}>
                        <td>{label}</td>
                        <td className="num mono">{group.length}</td>
                        <td className="num mono">{s.compared}</td>
                        <td className="num mono">{share(s.beat)}</td>
                        <td className="num mono">{pct(s.avgReturn, lang)}</td>
                        <td className="num mono">{pct(s.avgExcess, lang)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="help">{r.compareNote}</p>
            </section>
          )}

          <section className="panel section tbl-wrap">
            <header><h2>{r.ideas}</h2></header>
            <table>
              <thead>
                <tr>
                  <th>{r.cols.published}</th>
                  <th>{r.byWho}</th>
                  <th>{r.cols.stock}</th>
                  <th>{r.cols.confidence}</th>
                  {HORIZONS.map((h) => (
                    <th key={h} className="num">{r.days(h)}</th>
                  ))}
                  <th>{r.cols.thesis}</th>
                </tr>
              </thead>
              <tbody>
                {all.map((i) => (
                  <tr key={i.id}>
                    <td className="mono">{shortDate(i.briefing_date, lang)}</td>
                    <td>
                      {i.origin === "user" ? r.whoMe : r.whoAgent}
                      {i.origin === "user" && !i.entry_date && (
                        <form action={removeMyPick}>
                          <input type="hidden" name="id" value={i.id} />
                          <input type="hidden" name="back" value="/record" />
                          <button className="btn small" type="submit">{r.remove}</button>
                        </form>
                      )}
                    </td>
                    <td>
                      <CompanyLink k={i.key} name={i.name} />
                      <div className="ticker">{i.benchmark}</div>
                    </td>
                    <td>{i.confidence ? t.confidence[i.confidence] : "–"}</td>
                    {HORIZONS.map((h) => (
                      <td key={h} className="num mono">
                        {i.outcomes[String(h)] ? (
                          <Result o={i.outcomes[String(h)]} lang={lang} vs={r.vsIndex} />
                        ) : (
                          <span className="muted">{i.entry_date ? r.pending : r.noPrices}</span>
                        )}
                      </td>
                    ))}
                    <td style={{ minWidth: "16rem" }}>{i.thesis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </>
  );
}
