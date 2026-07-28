"use client";

/* eslint-disable @next/next/no-img-element */

import { useState } from "react";

export function AvatarImage({
  avatarKey,
  displayName,
  className = "",
  decorative = false,
}: {
  avatarKey: string | null;
  displayName: string;
  className?: string;
  decorative?: boolean;
}) {
  const [failedSource, setFailedSource] = useState("");

  const classes = ["avatar", className].filter(Boolean).join(" ");
  const fallback = displayName.trim().slice(0, 1) || "用";
  const source = avatarKey ? `/avatars/${avatarKey}.webp` : "";
  return (
    <span
      className={classes}
      aria-label={decorative ? undefined : `${displayName}的头像`}
      aria-hidden={decorative || undefined}
    >
      {avatarKey && failedSource !== source ? (
        <img
          src={source}
          alt=""
          onError={() => setFailedSource(source)}
        />
      ) : (
        fallback
      )}
    </span>
  );
}

export function AvatarOptionPreview({
  avatarKey,
  label,
}: {
  avatarKey: string;
  label: string;
}) {
  const [failedSource, setFailedSource] = useState("");
  const [style, character = "01"] = avatarKey.split("-");
  const source = `/avatars/${avatarKey}.webp`;
  return (
    <span
      className={`avatar-option-preview avatar-option-${style}`}
      aria-label={label}
    >
      {failedSource !== source ? (
        <img
          src={source}
          alt=""
          onError={() => setFailedSource(source)}
        />
      ) : (
        <>
          <i aria-hidden="true" />
          <b>{character}</b>
        </>
      )}
    </span>
  );
}
