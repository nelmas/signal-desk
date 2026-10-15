// First gate: every page needs a valid session, otherwise go to /login.
// Data access checks the session again (lib/session.ts), so a gap here can't leak data.

import { NextResponse, type NextRequest } from "next/server";
import { authConfig, isValidSessionToken, SESSION_COOKIE } from "@/lib/auth";

export function proxy(request: NextRequest) {
  const { secret } = authConfig();
  if (isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value, secret)) {
    return NextResponse.next();
  }
  const login = new URL("/login", request.url);
  const wanted = request.nextUrl.pathname + request.nextUrl.search;
  if (wanted !== "/") login.searchParams.set("next", wanted);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except the login page itself and static build files.
  matcher: ["/((?!login|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
