import type { Metadata } from "next";
import { getDict } from "@/lib/lang";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Log in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const [{ next }, { t }] = await Promise.all([searchParams, getDict()]);
  return (
    <div className="login">
      <LoginForm next={next ?? "/"} t={t.login} brand={t.brand} />
    </div>
  );
}
