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
      "style-src 'self' 'unsafe-inline' https://g.alicdn.com/captcha-frontend/ https://x.alicdn.com/captcha-frontend/",
      "script-src 'self' 'unsafe-inline' https://o.alicdn.com https://g.alicdn.com https://x.alicdn.com https://static-captcha.aliyuncs.com",
      // The SDK fetches embedded image data as well as its device verification endpoint.
      "connect-src 'self' data: https://*.captcha-open.aliyuncs.com https://*.captcha-open-b.aliyuncs.com https://cloudauth-device.aliyuncs.com https://cloudauth-device-dualstack.cn-shanghai.aliyuncs.com https://cn-shanghai.device.saf.aliyuncs.com https://o.alicdn.com https://g.alicdn.com https://x.alicdn.com https://static-captcha.aliyuncs.com",
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
  // vinext checks multipart POSTs before dispatching API routes. The proxy still
  // enforces 256 KiB elsewhere and 5 MiB + multipart overhead only for avatars.
  experimental: { serverActions: { bodySizeLimit: 5 * 1024 * 1024 + 64 * 1024 } },
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
