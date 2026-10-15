"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  authConfig,
  createSessionToken,
  passwordMatches,
  safeNextPath,
  SESSION_COOKIE,
  SESSION_DAYS,
} from "@/lib/auth";

export type LoginState = { wrong: boolean };

export async function login(_prev: LoginState, form: FormData): Promise<LoginState> {
  const { password, secret } = authConfig();
  if (!passwordMatches(String(form.get("password") ?? ""), password)) {
    // Slow down guessing; one person never needs to try twice a second.
    await new Promise((resolve) => setTimeout(resolve, 1200));
    return { wrong: true };
  }
  (await cookies()).set(SESSION_COOKIE, createSessionToken(secret), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_DAYS * 24 * 60 * 60,
  });
  redirect(safeNextPath(String(form.get("next") ?? "")));
}

export async function logout(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
