import { describe, expect, it } from "vitest";
import { makeCursor, parseCursor } from "./paging";

describe("news cursor", () => {
  it("round-trips and rejects anything else", () => {
    expect(parseCursor(makeCursor("2026-10-14T18:02:00Z", 42))).toEqual(["2026-10-14T18:02:00Z", 42]);
    for (const bad of [null, "", "2026-10-14", "2026-10-14T18:02:00Z", "x~1", "2026-10-14T18:02:00Z~1;drop"]) {
      expect(parseCursor(bad)).toBeNull();
    }
  });
});
