// The interface language follows the briefing language from Settings. Only that one
// value is read here, without a session, so the login page can use it too.

import "server-only";
import { cache } from "react";
import { db } from "@/lib/db";
import { asLang, dict, type Dict, type Lang } from "@/lib/i18n";

export const getLang = cache(async (): Promise<Lang> => {
  try {
    const rows = await db().query(
      `select value->>'language' as language from settings where key = 'briefing'`,
    );
    return asLang(rows[0]?.language);
  } catch {
    return "en";
  }
});

export async function getDict(): Promise<{ lang: Lang; t: Dict }> {
  const lang = await getLang();
  return { lang, t: dict(lang) };
}
