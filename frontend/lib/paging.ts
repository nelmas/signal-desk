// News feed paging: the cursor is the last row shown, so equal timestamps are never skipped.

export function parseCursor(before: string | null): [string, number] | null {
  const m = before?.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)~(\d+)$/);
  return m ? [m[1], Number(m[2])] : null;
}

export function makeCursor(publishedAt: string, id: number): string {
  return `${publishedAt}~${id}`;
}
