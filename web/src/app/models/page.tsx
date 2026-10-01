import fs from "node:fs/promises";
import path from "node:path";
import type { Metadata } from "next";
import ModelTrack, { type Milestone, type Models } from "@/components/ModelTrack";

export const metadata: Metadata = {
  title: "How fast the models moved",
  description: "Foundation-model progress 2017-2026: every benchmark, every lab, one timeline.",
};

export default async function Page() {
  const data: Models = JSON.parse(
    await fs.readFile(path.join(process.cwd(), "public", "data", "models.json"), "utf8")
  );
  const positions: { events: Milestone[] } = JSON.parse(
    await fs.readFile(path.join(process.cwd(), "public", "data", "positions.json"), "utf8")
  );
  const events = positions.events.filter((e) => ["Models", "Research", "Scaling"].includes(e.category));
  return <ModelTrack data={data} events={events} />;
}
