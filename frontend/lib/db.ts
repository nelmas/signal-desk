import "server-only";
import { neon, type NeonQueryFunction } from "@neondatabase/serverless";

let client: NeonQueryFunction<false, false> | undefined;

/** Neon's HTTP driver: one request per query, nothing to keep open on serverless hosts. */
export function db(): NeonQueryFunction<false, false> {
  if (!client) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");
    // The backend may use SQLAlchemy's "postgresql+psycopg://" form; the driver wants plain.
    client = neon(url.replace(/^postgres(ql)?\+\w+:\/\//, "postgresql://"));
  }
  return client;
}
