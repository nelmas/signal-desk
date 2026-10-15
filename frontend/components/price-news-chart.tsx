"use client";

// Two panels on one time axis: closing price above, articles per day below.
// Never two y-scales on one plot. Hover shows the day's numbers in both.

import { useRef, useState } from "react";
import { countAxis, priceDomain, ticks, type ChartDay } from "@/lib/chart";

const W = 760;
const L = 52;
const R = 14;
const TOP1 = 16;
const H1 = 170;
const TOP2 = 228;
const H2 = 84;
const HEIGHT = TOP2 + H2 + 26;

function label(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric", month: "short", timeZone: "UTC",
  });
}

export function PriceNewsChart({ days, currency }: { days: ChartDay[]; currency: string | null }) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const n = days.length;
  const slot = (W - L - R) / n;
  const x = (i: number) => L + (i + 0.5) * slot;

  const closes = days.flatMap((d) => (d.close === null ? [] : [d.close]));
  const [lo, hi] = priceDomain(closes);
  const yP = (v: number) => TOP1 + H1 - ((v - lo) / (hi - lo)) * H1;
  const { top: nMax, ticks: nTicks } = countAxis(Math.max(0, ...days.map((d) => d.articles)));
  const yN = (v: number) => TOP2 + H2 - (v / nMax) * H2;

  // Connect trading days across weekends: the line follows days that have a close.
  const pts = days.map((d, i) => (d.close === null ? null : `${x(i)},${yP(d.close)}`)).filter(Boolean);
  const lastPrice = [...days.keys()].reverse().find((i) => days[i].close !== null);
  const bw = Math.max(1, slot - 2);
  const labelDays = [0, Math.floor(n / 3), Math.floor((2 * n) / 3), n - 1];

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box) return;
    const sx = ((e.clientX - box.left) / box.width) * W;
    setHover(Math.max(0, Math.min(n - 1, Math.floor((sx - L) / slot))));
  }

  const h = hover === null ? null : days[hover];
  return (
    <div className="chart-wrap">
      <svg
        ref={svgRef}
        className="chart"
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Closing price${currency ? ` in ${currency}` : ""} and tagged articles per day, last ${n} days`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <text className="label" x={L} y={TOP1 - 4}>
          Close{currency ? `, ${currency}` : ""}
        </text>
        {closes.length > 0 ? (
          <>
            {ticks([lo, hi]).map((v) => (
              <g key={`p${v}`}>
                <line x1={L} x2={W - R} y1={yP(v)} y2={yP(v)} stroke="var(--line)" />
                <text x={L - 8} y={yP(v) + 4} textAnchor="end">
                  {v}
                </text>
              </g>
            ))}
            <polyline points={pts.join(" ")} fill="none" stroke="var(--accent)" strokeWidth={2}
              strokeLinejoin="round" />
            {lastPrice !== undefined && (
              <circle cx={x(lastPrice)} cy={yP(days[lastPrice].close!)} r={4.5} fill="var(--accent)"
                stroke="var(--surface)" strokeWidth={2} />
            )}
          </>
        ) : (
          <text x={(L + W) / 2} y={TOP1 + H1 / 2} textAnchor="middle">
            No price data for this stock
          </text>
        )}

        <text className="label" x={L} y={TOP2 - 8}>
          Tagged articles per day
        </text>
        {nTicks.map((v) => (
          <g key={`n${v}`}>
            <line x1={L} x2={W - R} y1={yN(v)} y2={yN(v)} stroke="var(--line)" />
            <text x={L - 8} y={yN(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {days.map((d, i) =>
          d.articles > 0 ? (
            <path
              key={d.day}
              d={`M${x(i) - bw / 2},${TOP2 + H2} V${yN(d.articles) + 2} q0,-2 2,-2 h${bw - 4} q2,0 2,2 V${TOP2 + H2} Z`}
              fill="var(--score)"
              opacity={i === n - 1 || i === hover ? 1 : 0.55}
            />
          ) : null,
        )}
        {labelDays.map((i) => (
          <text key={`d${i}`} x={x(i)} y={TOP2 + H2 + 18} textAnchor="middle">
            {label(days[i].day)}
          </text>
        ))}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={TOP1} y2={TOP2 + H2} stroke="var(--ink-3)"
            strokeDasharray="3 3" />
        )}
        <rect x={L} y={TOP1} width={W - L - R} height={TOP2 + H2 - TOP1} fill="transparent" />
      </svg>
      {h && hover !== null && (
        <div
          className="tip"
          style={{ left: `${(x(hover) / W) * 100}%`, top: `${((h.close !== null ? yP(h.close) : TOP2) / HEIGHT) * 100}%` }}
        >
          {label(h.day)}
          <br />
          {h.close !== null ? `Close ${h.close.toFixed(2)}` : "No trading"}
          <br />
          {h.articles} article{h.articles === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}
