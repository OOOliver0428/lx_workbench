import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "协作工作台",
  description: "以项目为核心的团队协作、任务推进与工作记录平台。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
