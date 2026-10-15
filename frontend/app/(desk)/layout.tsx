import Link from "next/link";
import { Nav } from "@/components/nav";
import { logout } from "@/app/login/actions";
import { requireSession } from "@/lib/session";

export default async function DeskLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  return (
    <div className="wrap">
      <header className="top">
        <Link href="/" className="brand">
          <span className="lamp" aria-hidden="true" />
          Signal Desk
        </Link>
        <div className="meta">
          <span>Ideas to research, not advice</span>
          <form action={logout}>
            <button type="submit" className="linkish">
              Log out
            </button>
          </form>
        </div>
      </header>
      <div className="shell">
        <Nav />
        <main>{children}</main>
      </div>
    </div>
  );
}
