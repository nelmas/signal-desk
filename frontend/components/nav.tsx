"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Dict } from "@/lib/i18n";

const LINKS = [
  { href: "/", key: "briefing" },
  { href: "/watchlist", key: "watchlist" },
  { href: "/news", key: "news" },
  { href: "/radar", key: "radar" },
  { href: "/record", key: "record" },
  { href: "/settings", key: "settings" },
] as const;

export function Nav({ labels }: { labels: Dict["nav"] }) {
  const path = usePathname();
  const current = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <nav className="tabs" aria-label={labels.sections}>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} aria-current={current(l.href) ? "page" : undefined}>
          {labels[l.key]}
        </Link>
      ))}
    </nav>
  );
}
