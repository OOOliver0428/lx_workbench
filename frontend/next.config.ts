const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "base-uri 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "form-action 'self'",
      "img-src 'self' data: blob: https://*.alicdn.com https://static-captcha.aliyuncs.com",
      "font-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      "script-src 'self' 'unsafe-inline' https://o.alicdn.com https://g.alicdn.com https://x.alicdn.com https://static-captcha.aliyuncs.com",
      "connect-src 'self' https://*.captcha-open.aliyuncs.com https://*.captcha-open-b.aliyuncs.com https://cloudauth-device.aliyuncs.com https://cn-shanghai.device.saf.aliyuncs.com https://o.alicdn.com https://g.alicdn.com https://x.alicdn.com https://static-captcha.aliyuncs.com",
      "worker-src 'self' blob:",
    ].join("; "),
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  {
    key: "Permissions-Policy",
    value: "camera=(), geolocation=(), microphone=()",
  },
];

const nextConfig = {
  async headers() {
    return [
      {
        source: "/images/login/optimized/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
