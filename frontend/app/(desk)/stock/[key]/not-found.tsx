import Link from "next/link";

export default function StockNotFound() {
  return (
    <div className="view-head">
      <span className="eyebrow">Stock</span>
      <h1>Not on the list</h1>
      <p>
        The app only knows companies on its verified list. <Link href="/watchlist">Back to the
        watchlist</Link>.
      </p>
    </div>
  );
}
