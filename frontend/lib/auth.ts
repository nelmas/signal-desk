// Single-user login: a password from APP_PASSWORD and a signed, expiring session cookie.
// Changing SESSION_SECRET logs out every browser at once.

import { createHash, createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "sd_session";
export const SESSION_DAYS = 30;
const DAY_MS = 24 * 60 * 60 * 1000;
const VERSION = "v1";

export type AuthConfig = { password: string; secret: string };

export function authConfig(env: Record<string, string | undefined> = process.env): AuthConfig {
  const password = env.APP_PASSWORD ?? "";
  const secret = env.SESSION_SECRET ?? "";
  // Fail closed: without both, nobody can log in (rather than everybody).
  if (password.length < 8) throw new Error("APP_PASSWORD must be set (8+ characters)");
  if (secret.length < 32) throw new Error("SESSION_SECRET must be set (32+ characters)");
  return { password, secret };
}

function sign(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

function sameBytes(a: Buffer, b: Buffer): boolean {
  return a.length === b.length && timingSafeEqual(a, b);
}

export function createSessionToken(secret: string, now = Date.now()): string {
  const payload = `${VERSION}.${now + SESSION_DAYS * DAY_MS}`;
  return `${payload}.${sign(payload, secret)}`;
}

export function isValidSessionToken(
  token: string | undefined,
  secret: string,
  now = Date.now(),
): boolean {
  if (!token) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== VERSION) return false;
  const payload = `${parts[0]}.${parts[1]}`;
  const expected = Buffer.from(sign(payload, secret));
  if (!sameBytes(Buffer.from(parts[2]), expected)) return false;
  const expires = Number(parts[1]);
  return Number.isFinite(expires) && expires > now;
}

export function passwordMatches(given: string, expected: string): boolean {
  // Hash first so the comparison takes the same time whatever the lengths.
  const digest = (s: string) => createHash("sha256").update(s, "utf8").digest();
  return sameBytes(digest(given), digest(expected));
}

/** Only same-site paths, so the login page can't be used to bounce to another site. */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/";
  }
  return next;
}
