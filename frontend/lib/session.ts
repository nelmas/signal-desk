// Second gate, used by every data query and server action.

import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { authConfig, isValidSessionToken, SESSION_COOKIE } from "@/lib/auth";

export async function requireSession(): Promise<void> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!isValidSessionToken(token, authConfig().secret)) redirect("/login");
}
