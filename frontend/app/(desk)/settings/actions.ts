"use server";

// Every action checks the session (inside the settings helpers) and validates its input
// before writing. Results come back as ?saved=<section> or ?error=<message key>.

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  getSettingsData,
  saveSetting,
  unwatch,
  updateWatch,
  watchCompany,
} from "@/lib/settings";
import { parseBriefing, parseEmail, parseNote, parseToggles, parseWeights } from "@/lib/validate";

function done(section: string, error?: string): never {
  revalidatePath("/", "layout");
  const qs = error ? `error=${encodeURIComponent(error)}` : `saved=${section}`;
  redirect(`/settings?${qs}#${section}`);
}

function companyId(form: FormData): number {
  const id = Number(form.get("company_id"));
  if (!Number.isInteger(id) || id <= 0) done("watchlist", "company");
  return id;
}

export async function saveWeights(form: FormData): Promise<void> {
  const r = parseWeights(form);
  if (!r.ok) done("weights", r.error);
  await saveSetting("scoring_weights", r.value);
  done("weights");
}

export async function saveBriefing(form: FormData): Promise<void> {
  const { briefing } = await getSettingsData();
  const r = parseBriefing(form, briefing);
  if (!r.ok) done("briefing", r.error);
  await saveSetting("briefing", r.value);
  done("briefing");
}

export async function saveEmail(form: FormData): Promise<void> {
  const r = parseEmail(form);
  if (!r.ok) done("email", r.error);
  await saveSetting("email", r.value);
  done("email");
}

export async function saveSources(form: FormData): Promise<void> {
  const { sources, markets } = await getSettingsData();
  const sourceOn = parseToggles(form, sources.map((s) => s.key));
  const marketOn = parseToggles(form, markets.map((m) => `market_${m.key}`));
  if (!Object.values(sourceOn).some(Boolean)) done("sources", "sources_none");
  await saveSetting("sources", sourceOn);
  await saveSetting(
    "markets",
    Object.fromEntries(markets.map((m) => [m.key, marketOn[`market_${m.key}`]])),
  );
  done("sources");
}

export async function addToWatchlist(form: FormData): Promise<void> {
  await watchCompany(companyId(form), form.get("holding") === "on");
  done("watchlist");
}

export async function editWatch(form: FormData): Promise<void> {
  await updateWatch(companyId(form), form.get("holding") === "on", parseNote(form.get("note")));
  done("watchlist");
}

export async function removeFromWatchlist(form: FormData): Promise<void> {
  await unwatch(companyId(form));
  done("watchlist");
}
