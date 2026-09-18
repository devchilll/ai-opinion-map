import fs from "node:fs/promises";
import path from "node:path";
import BeliefMap, { type Credit, type Positions } from "@/components/BeliefMap";

async function readJson<T>(...parts: string[]): Promise<T> {
  return JSON.parse(await fs.readFile(path.join(process.cwd(), ...parts), "utf8"));
}

export default async function Page() {
  const data = await readJson<Positions>("public", "data", "positions.json");
  const credits = await readJson<Record<string, Credit>>(
    "public", "data", "portrait_credits.json"
  ).catch(() => ({}));
  return <BeliefMap data={{ ...data, credits }} />;
}
