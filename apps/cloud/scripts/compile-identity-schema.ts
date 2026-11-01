import { writeFile } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { getMigrations } from "better-auth/db/migration";
import { createIdentity } from "../src/identity.js";

const address=process.env.TEST_DATABASE_URL;
if (!address) throw new Error("TEST_DATABASE_URL must reference a disposable PostgreSQL database");
const pool=new pg.Pool({connectionString: address});
try {
  const identity=createIdentity({
    publicOrigin:"http://127.0.0.1:8787",
    audience:"http://127.0.0.1:8787/mcp",
    databaseUrl:address
  },{
    secret:randomBytes(48).toString("hex"),
    googleId:"test-id",googleSecret:"test-value",
    githubId:"test-id",githubSecret:"test-value"
  },pool);
  const migration=await getMigrations(identity.options);
  if (migration.unsafeChanges.length) throw new Error("Unsafe migration must be reviewed");
  const sql=await migration.compileMigrations();
  if (!sql.includes("oauthClient") || !sql.includes("oauthAccessToken")) throw new Error("Auth schema output incomplete");
  await writeFile("db/003_better_auth.pgsql","-- Generated with Better Auth 1.7.13; review before applying.\n"+sql+"\n",{flag:"wx"});
  process.stdout.write("Reviewed identity migration candidate generated.\n");
} finally {
  await pool.end();
}
