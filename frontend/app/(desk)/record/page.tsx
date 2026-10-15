import type { Metadata } from "next";
import { CompanyLink } from "@/components/bits";
import { shortDate } from "@/lib/format";
import { getDict } from "@/lib/lang";
import { getIdeas } from "@/lib/queries";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDict()).t.nav.record };
}

export default async function RecordPage() {
  const [ideas, { lang, t }] = await Promise.all([getIdeas(), getDict()]);
  const r = t.record;
  return (
    <>
      <div className="view-head">
        <span className="eyebrow">{r.eyebrow}</span>
        <h1>{r.title}</h1>
        <p>{r.intro}</p>
      </div>
      <div className="panel tbl-wrap">
        {ideas.length === 0 ? (
          <p className="empty">{r.empty}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{r.cols.published}</th>
                <th>{r.cols.stock}</th>
                <th>{r.cols.confidence}</th>
                <th>{r.cols.thesis}</th>
                <th>{r.cols.index}</th>
              </tr>
            </thead>
            <tbody>
              {ideas.map((i) => (
                <tr key={i.id}>
                  <td className="mono">{shortDate(i.briefing_date, lang)}</td>
                  <td>
                    <CompanyLink k={i.key} name={i.name} />
                  </td>
                  <td>{t.confidence[i.confidence as keyof typeof t.confidence] ?? i.confidence}</td>
                  <td style={{ minWidth: "18rem" }}>{i.thesis}</td>
                  <td className="muted">{i.benchmark}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
