export const MAX_AVATAR_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_AVATAR_REQUEST_BYTES = MAX_AVATAR_FILE_BYTES + 64 * 1024;

export interface AvatarStatus {
  availability: "ready" | "disabled" | "unavailable";
  phone_bound: boolean;
  can_upload: boolean;
  max_file_bytes: number;
  output_size: number;
  formats: string[];
}

export interface AvatarCrop {
  x: number;
  y: number;
  size: number;
}

export function avatarSource(key: string | null): string {
  if (!key) return "";
  const custom = /^custom-([0-9a-f]{32})$/.exec(key);
  if (custom) return `/api/v1/avatars/${custom[1]}`;
  return /^[a-z-]+-[0-9]{2}$/.test(key) ? `/avatars/${key}.webp` : "";
}

export function validateAvatarFile(file: Pick<File, "size" | "type">): string {
  if (!file.size) return "图片文件为空，请重新选择。";
  if (file.size > MAX_AVATAR_FILE_BYTES) return "请选择不超过 5 MiB 的图片。";
  if (file.type && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    return "请选择 JPG、PNG 或静态 WebP 图片。";
  }
  return "";
}

export function avatarCropGeometry(
  width: number, height: number, zoom: number, horizontal: number, vertical: number,
): { crop: AvatarCrop; left: number; top: number; edge: number } {
  if (![width, height, zoom, horizontal, vertical].every(Number.isFinite) || width < 1 || height < 1) {
    throw new RangeError("invalid image dimensions or crop parameters");
  }
  const scale = Math.max(1, Math.min(4, zoom));
  const edge = Math.max(1, Math.floor(Math.min(width, height) / scale));
  const left = Math.floor((width - edge) * Math.max(0, Math.min(100, horizontal)) / 100);
  const top = Math.floor((height - edge) * Math.max(0, Math.min(100, vertical)) / 100);
  return { left, top, edge, crop: { x: left / width, y: top / height, size: edge / Math.min(width, height) } };
}

// Route-specific limit; the rest of the API retains its configured JSON body limit.
export function avatarRequestLimit(pathname: string, defaultLimit: number): number {
  return pathname === "/api/v1/profile/avatar/upload" ? MAX_AVATAR_REQUEST_BYTES : defaultLimit;
}
