import fs from "node:fs/promises";
import path from "node:path";
import type { Metadata } from "next";
import ModelTrack, { type Models } from "@/components/ModelTrack";

export const metadata: Metadata = {
  title: "How fast the models moved",
  description: "Foundation-model progress 2017-2026: every benchmark, every lab, one timeline.",
};

export default async function Page() {
  const data: Models = JSON.parse(
    await fs.readFile(path.join(process.cwd(), "public", "data", "models.json"), "utf8")
  );
  return <ModelTrack data={data} />;
}
