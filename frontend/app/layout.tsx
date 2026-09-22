import "./globals.css";

export const metadata = {
  title: "协作工作台",
  description: "以项目为核心的团队协作、任务推进与工作记录平台。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

const themeInit = `(function(){try{var m=localStorage.getItem('workbench-theme')||'system';var r=document.documentElement;r.dataset.theme=m;var d=m==='dark'||(m==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.themeResolved=d?'dark':'light';r.style.colorScheme=d?'dark':'light';}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
