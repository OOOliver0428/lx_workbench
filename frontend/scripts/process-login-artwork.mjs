import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import sharp from "sharp";

const root = new URL("../", import.meta.url);
const output = new URL("public/images/login/optimized/", root);
await mkdir(output, { recursive: true });
const assets = {};
let before = 0;
let after = 0;
for (const name of ["blue-ribbon-v3", "opportunities", "tasks", "work", "reports"]) {
  const source = await readFile(new URL(`public/images/login/${name}.png`, root));
  const encoded = await sharp(source)
    .webp(name === "blue-ribbon-v3" ? { quality: 90, effort: 6 } : { lossless: true, effort: 6 })
    .toBuffer();
  const hash = createHash("sha256").update(encoded).digest("hex").slice(0, 12);
  const filename = `${name}.${hash}.webp`;
  await writeFile(new URL(filename, output), encoded);
  assets[name] = `/images/login/optimized/${filename}`;
  before += source.length;
  after += encoded.length;
}
await writeFile(new URL("app/login-artwork.json", root), `${JSON.stringify(assets, null, 2)}\n`);
console.log(`Login artwork: ${before} → ${after} bytes (${Math.round((1 - after / before) * 100)}% smaller)`);
