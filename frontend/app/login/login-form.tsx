"use client";

import { useActionState } from "react";
import type { Dict } from "@/lib/i18n";
import { login, type LoginState } from "./actions";

export function LoginForm({ next, t, brand }: { next: string; t: Dict["login"]; brand: string }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(login, { wrong: false });
  return (
    <form action={action}>
      <div className="brand">
        <span className="lamp" aria-hidden="true" />
        {brand}
      </div>
      <label htmlFor="password" className="eyebrow">
        {t.password}
      </label>
      <input
        id="password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        autoFocus
      />
      <input type="hidden" name="next" value={next} />
      {state.wrong && (
        <p className="error" role="alert">
          {t.wrong}
        </p>
      )}
      <button className="btn" type="submit" disabled={pending}>
        {pending ? t.checking : t.submit}
      </button>
    </form>
  );
}
