import Link from "next/link";
import { getDict } from "@/lib/lang";

export default async function StockNotFound() {
  const { t } = await getDict();
  return (
    <div className="view-head">
      <span className="eyebrow">{t.stock.eyebrow}</span>
      <h1>{t.stock.notFoundTitle}</h1>
      <p>
        {t.stock.notFoundText} <Link href="/watchlist">{t.stock.back}</Link>.
      </p>
    </div>
  );
}
