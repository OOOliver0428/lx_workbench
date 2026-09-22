import "./globals.css";
import loginArtwork from "./login-artwork.json";

export const metadata = {
  title: "协作工作台",
  description: "以项目为核心的团队协作、任务推进与工作记录平台。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

const themeInit = `(function(){try{var m=localStorage.getItem('workbench-theme')||'system';var d=m==='dark'||(m!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);var r=document.documentElement;r.dataset.theme=d?'dark':'light';r.style.colorScheme=d?'dark':'light';}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
        {/* Start the two prominent images before the client session check.
            The artwork is hidden on narrow screens, so do not preload there. */}
        <link rel="preload" as="image" type="image/webp" href={loginArtwork["blue-ribbon-v3"]} media="(min-width: 861px)" />
        <link rel="preload" as="image" type="image/webp" href={loginArtwork.opportunities} media="(min-width: 861px)" />
      </head>
      <body>{children}</body>
    </html>
  );
}
