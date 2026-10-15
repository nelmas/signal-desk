import { describe, expect, it } from "vitest";
import {
  authConfig,
  createSessionToken,
  isValidSessionToken,
  passwordMatches,
  safeNextPath,
  SESSION_DAYS,
} from "./auth";

const SECRET = "x".repeat(40);
const NOW = Date.UTC(2026, 9, 15);

describe("session tokens", () => {
  it("accepts a fresh token and rejects it after expiry", () => {
    const token = createSessionToken(SECRET, NOW);
    expect(isValidSessionToken(token, SECRET, NOW + 1000)).toBe(true);
    const later = NOW + (SESSION_DAYS + 1) * 24 * 60 * 60 * 1000;
    expect(isValidSessionToken(token, SECRET, later)).toBe(false);
  });

  it("rejects tampered, foreign and malformed tokens", () => {
    const token = createSessionToken(SECRET, NOW);
    const [v, exp, sig] = token.split(".");
    expect(isValidSessionToken(`${v}.${Number(exp) + 99999999}.${sig}`, SECRET, NOW)).toBe(false);
    expect(isValidSessionToken(token, "y".repeat(40), NOW)).toBe(false);
    for (const bad of [undefined, "", "v1.123", "v2.1.abc", "a.b.c.d"]) {
      expect(isValidSessionToken(bad, SECRET, NOW)).toBe(false);
    }
  });
});

describe("password and config", () => {
  it("compares passwords exactly", () => {
    expect(passwordMatches("correct horse", "correct horse")).toBe(true);
    expect(passwordMatches("correct hors", "correct horse")).toBe(false);
    expect(passwordMatches("", "correct horse")).toBe(false);
  });

  it("refuses to run without a real password and secret", () => {
    expect(() => authConfig({})).toThrow(/APP_PASSWORD/);
    expect(() => authConfig({ APP_PASSWORD: "long enough" })).toThrow(/SESSION_SECRET/);
    expect(authConfig({ APP_PASSWORD: "long enough", SESSION_SECRET: SECRET }).password).toBe(
      "long enough",
    );
  });
});

describe("safeNextPath", () => {
  it("only allows same-site paths", () => {
    expect(safeNextPath("/stock/volvo")).toBe("/stock/volvo");
    for (const bad of [null, "", "https://evil.example", "//evil.example", "/\\evil"]) {
      expect(safeNextPath(bad)).toBe("/");
    }
  });
});
