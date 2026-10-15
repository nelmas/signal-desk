import Link from "next/link";
import { Nav } from "@/components/nav";
import { logout } from "@/app/login/actions";
import { getDict } from "@/lib/lang";
import { requireSession } from "@/lib/session";

export default async function DeskLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  const { t } = await getDict();
  return (
    <div className="wrap">
      <header className="top">
        <Link href="/" className="brand">
          <span className="lamp" aria-hidden="true" />
          {t.brand}
        </Link>
        <div className="meta">
          <span>{t.tagline}</span>
          <form action={logout}>
            <button type="submit" className="linkish">
              {t.logout}
            </button>
          </form>
        </div>
      </header>
      <div className="shell">
        <Nav labels={t.nav} />
        <main>{children}</main>
      </div>
    </div>
  );
}
