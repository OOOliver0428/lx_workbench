import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const workspaceDirectory = path.resolve(frontendDirectory, "..");
const sourceDirectory = path.resolve(
  workspaceDirectory,
  process.env.AVATAR_SOURCE_DIR ?? ".static",
);
const outputDirectory = path.join(frontendDirectory, "public", "avatars");

const avatarSets = [
  {
    id: "flat",
    label: "极简扁平",
    directory: "极简扁平风",
    pixelArt: false,
  },
  {
    id: "clay-soft",
    label: "柔和黏土",
    directory: "轻黏土风",
    pixelArt: false,
  },
  {
    id: "pixel-soft",
    label: "简约像素",
    directory: "简像素风",
    pixelArt: true,
  },
  {
    id: "paper",
    label: "纸艺剪纸",
    directory: "纸艺剪纸风",
    pixelArt: false,
  },
  {
    id: "line",
    label: "手绘涂鸦",
    directory: "手绘涂鸦风",
    pixelArt: false,
  },
  {
    id: "pixel",
    label: "深色像素",
    directory: "像素风",
    pixelArt: true,
  },
  {
    id: "clay",
    label: "立体黏土",
    directory: "黏土风",
    pixelArt: false,
  },
];

await mkdir(outputDirectory, { recursive: true });

const catalog = [];
for (const avatarSet of avatarSets) {
  const setDirectory = path.join(sourceDirectory, avatarSet.directory);
  const files = (await readdir(setDirectory))
    .filter((name) => name.toLowerCase().endsWith(".png"))
    .sort((left, right) =>
      left.localeCompare(right, "zh-CN", {
        numeric: true,
        sensitivity: "base",
      }),
    );

  if (files.length !== 8) {
    throw new Error(
      `${avatarSet.directory} 应包含 8 张 PNG，当前检测到 ${files.length} 张`,
    );
  }

  for (const [index, filename] of files.entries()) {
    const sourcePath = path.join(setDirectory, filename);
    const character = index + 1;
    const id = `${avatarSet.id}-${String(character).padStart(2, "0")}`;
    const outputFilename = `${id}.webp`;
    const outputPath = path.join(outputDirectory, outputFilename);
    const image = sharp(sourcePath, { failOn: "error" }).rotate();
    const metadata = await image.metadata();

    if (
      !metadata.width ||
      !metadata.height ||
      metadata.width !== metadata.height ||
      metadata.width < 512
    ) {
      throw new Error(
        `${path.relative(workspaceDirectory, sourcePath)} 必须是至少 512px 的正方形图片`,
      );
    }

    await image
      .resize(512, 512, {
        fit: "cover",
        position: "centre",
        kernel: avatarSet.pixelArt ? sharp.kernel.nearest : sharp.kernel.lanczos3,
      })
      .webp({
        quality: 86,
        smartSubsample: true,
        effort: 6,
      })
      .toFile(outputPath);

    catalog.push({
      id,
      label: `形象 ${String(character).padStart(2, "0")} · ${avatarSet.label}`,
      style: avatarSet.id,
      style_label: avatarSet.label,
      character,
      url: `/avatars/${outputFilename}`,
      source: path
        .relative(workspaceDirectory, sourcePath)
        .split(path.sep)
        .join("/"),
    });
  }
}

await writeFile(
  path.join(outputDirectory, "catalog.json"),
  `${JSON.stringify(catalog, null, 2)}\n`,
  "utf8",
);

console.log(
  `Processed ${catalog.length} avatars into ${path.relative(
    workspaceDirectory,
    outputDirectory,
  )}`,
);
