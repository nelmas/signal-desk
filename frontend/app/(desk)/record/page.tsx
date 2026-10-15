import type { Metadata } from "next";
import { CompanyLink } from "@/components/bits";
import { shortDate } from "@/lib/format";
import { getIdeas } from "@/lib/queries";

export const metadata: Metadata = { title: "Track record" };

export default async function RecordPage() {
  const ideas = await getIdeas();
  return (
    <>
      <div className="view-head">
        <span className="eyebrow">Track record</span>
        <h1>Is the agent any good?</h1>
        <p>
          Every idea is logged the moment it is published. From phase 8, each one is checked
          after 1, 5 and 20 trading days against its market index, entering at the next
          session&apos;s open so the record never counts a move you couldn&apos;t have acted on.
        </p>
      </div>
      <p className="notice">Results arrive with phase 8. Until then this is the log of ideas.</p>
      <div className="panel tbl-wrap">
        {ideas.length === 0 ? (
          <p className="empty">No ideas logged yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Published</th>
                <th>Stock</th>
                <th>Confidence</th>
                <th>Why it could rise</th>
                <th>Index</th>
              </tr>
            </thead>
            <tbody>
              {ideas.map((i) => (
                <tr key={i.id}>
                  <td className="mono">{shortDate(i.briefing_date)}</td>
                  <td>
                    <CompanyLink k={i.key} name={i.name} />
                  </td>
                  <td>{i.confidence}</td>
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
