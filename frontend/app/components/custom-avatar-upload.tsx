"use client";

import { useEffect, useRef, useState } from "react";
import { api, apiErrorMessage } from "../api";
import { avatarCropGeometry, validateAvatarFile } from "../avatar-upload";
import type { AvatarStatus } from "../avatar-upload";
import type { AuthContext } from "../types";
import { InlineNotice } from "./ui";

export function CustomAvatarUpload({ context, status, onSaved, onBusyChange, onCancel }: {
  context: AuthContext;
  status: AvatarStatus | null;
  onSaved: (context: AuthContext) => void;
  onBusyChange: (busy: boolean) => void;
  onCancel: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [horizontal, setHorizontal] = useState(50);
  const [vertical, setVertical] = useState(50);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const generationRef = useRef(0);

  useEffect(() => () => { generationRef.current += 1; }, []);

  useEffect(() => {
    if (!image || !canvasRef.current) return;
    const drawing = canvasRef.current.getContext("2d");
    if (!drawing) return;
    const { left, top, edge } = avatarCropGeometry(image.naturalWidth, image.naturalHeight, zoom, horizontal, vertical);
    drawing.clearRect(0, 0, 512, 512);
    drawing.drawImage(image, left, top, edge, edge, 0, 0, 512, 512);
  }, [image, zoom, horizontal, vertical]);

  async function selectFile(candidate: File | undefined) {
    if (!candidate || busy) return;
    const generation = ++generationRef.current;
    setError(""); setFile(null); setImage(null); setLoading(false);
    const invalid = validateAvatarFile(candidate);
    if (invalid) { setError(invalid); return; }
    setLoading(true);
    const url = URL.createObjectURL(candidate);
    try {
      const preview = new Image();
      preview.src = url;
      await preview.decode();
      if (generation !== generationRef.current) return;
      if (preview.naturalWidth * preview.naturalHeight > 20_000_000) {
        setError("图片像素过多，请选择不超过 2000 万像素的图片。");
        return;
      }
      setZoom(1); setHorizontal(50); setVertical(50);
      setFile(candidate); setImage(preview);
    } catch {
      if (generation === generationRef.current) setError("图片无法读取，请重新选择。");
    } finally {
      URL.revokeObjectURL(url);
      if (generation === generationRef.current) setLoading(false);
    }
  }

  async function save() {
    if (!file || !image || busy || !status?.can_upload) return;
    setBusy(true); onBusyChange(true); setError("");
    try {
      const { crop } = avatarCropGeometry(image.naturalWidth, image.naturalHeight, zoom, horizontal, vertical);
      const user = await api.profile.uploadAvatar(context.user.revision, file, crop);
      onSaved({ ...context, user });
    } catch (caught) {
      setError(apiErrorMessage(caught, "头像上传失败，请稍后重试。"));
    } finally {
      setBusy(false); onBusyChange(false);
    }
  }

  return (
    <section className="custom-avatar-upload" aria-label="上传自定义头像">
      <p>选择图片并调整裁剪，保存后更新头像。支持 JPG、PNG、静态 WebP，最大 5 MiB。</p>
      {!status ? <InlineNotice>正在读取上传资格…</InlineNotice> : null}
      {status && status.availability !== "unavailable" && !status.phone_bound ? (
        <InlineNotice>请先在个人设置中完成手机号绑定，再上传自定义头像。</InlineNotice>
      ) : null}
      {status?.availability === "disabled" ? <InlineNotice>自定义头像上传暂未开放，仍可使用预设头像。</InlineNotice> : null}
      {status?.availability === "unavailable" ? <InlineNotice>自定义头像上传暂不可用，请稍后重试。</InlineNotice> : null}
      {status?.can_upload ? (
        <>
          <label className="avatar-file-label">
            选择头像图片
            <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy}
              onChange={(event) => {
                const selected = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                void selectFile(selected);
              }} />
          </label>
          {loading ? <p role="status">正在读取图片…</p> : null}
          {image ? (
            <div className="avatar-crop-editor">
              <div className="avatar-crop-preview">
                <canvas ref={canvasRef} width={512} height={512} role="img" aria-label="头像裁剪预览" />
                <small>圆形展示预览 · 保存为 512×512</small>
              </div>
              <div className="avatar-crop-controls">
                <label>缩放 {zoom.toFixed(1)}×
                  <input type="range" min={1} max={4} step={0.05} value={zoom} disabled={busy}
                    onChange={(event) => setZoom(Number(event.currentTarget.value))} />
                </label>
                <label>水平位置
                  <input type="range" min={0} max={100} value={horizontal} disabled={busy}
                    onChange={(event) => setHorizontal(Number(event.currentTarget.value))} />
                </label>
                <label>垂直位置
                  <input type="range" min={0} max={100} value={vertical} disabled={busy}
                    onChange={(event) => setVertical(Number(event.currentTarget.value))} />
                </label>
                <p>更换后不保留历史头像，请确认裁剪效果。</p>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      <footer className="modal-actions">
        <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>取消</button>
        <button type="button" className="primary-button" disabled={!status?.can_upload || !file || !image || busy || loading}
          onClick={() => void save()}>{busy ? "正在上传…" : "保存自定义头像"}</button>
      </footer>
    </section>
  );
}
