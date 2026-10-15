import Link from "next/link";

/** [1][2] markers that jump to the numbered source list on the same page. */
export function Cites({ ns, prefix = "src" }: { ns: number[]; prefix?: string }) {
  if (!ns.length) return null;
  return (
    <sup className="cite">
      {ns.map((n) => (
        <a key={n} href={`#${prefix}-${n}`}>
          [{n}]
        </a>
      ))}
    </sup>
  );
}

export function ScoreBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="bar" role="img" aria-label={label ?? `${pct.toFixed(0)} of 100`}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function CompanyLink({ k, name }: { k: string; name: string }) {
  return <Link href={`/stock/${encodeURIComponent(k)}`}>{name}</Link>;
}

const LEVELS = { low: 1, medium: 2, high: 3 } as const;

export function Confidence({ level }: { level: keyof typeof LEVELS }) {
  const on = LEVELS[level] ?? 1;
  return (
    <span className="conf" aria-label={`Confidence: ${level}`}>
      Confidence {[1, 2, 3].map((i) => <i key={i} className={i <= on ? "on" : undefined} />)} {level}
    </span>
  );
}
