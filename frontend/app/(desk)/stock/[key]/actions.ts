"use server";

// Your own picks: checked here, written by lib/picks. Results come back as
// ?pick=added or ?pick_error=<message key> on the page the form was on.

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { addPick, removePick } from "@/lib/picks";
import { parseReason } from "@/lib/validate";

function back(form: FormData, result: string | null, ok: string): never {
  revalidatePath("/", "layout");
  // Only our own paths: a stock page or Facit.
  const to = String(form.get("back") ?? "");
  const path = /^\/(stock\/[^/?#]+|record)$/.test(to) ? to : "/record";
  redirect(`${path}?${result ? `pick_error=${encodeURIComponent(result)}` : `pick=${ok}`}#pick`);
}

function positive(value: FormDataEntryValue | null): number | null {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export async function addMyPick(form: FormData): Promise<void> {
  const companyId = positive(form.get("company_id"));
  if (companyId === null) back(form, "company", "");
  const reason = parseReason(form.get("reason"));
  if (!reason.ok) back(form, reason.error, "");
  back(form, await addPick(companyId, reason.value), "added");
}

export async function removeMyPick(form: FormData): Promise<void> {
  const id = positive(form.get("id"));
  if (id === null) back(form, "started", "");
  back(form, await removePick(id), "removed");
}
