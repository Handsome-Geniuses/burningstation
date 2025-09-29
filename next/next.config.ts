import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    /* config options here */
    allowedDevOrigins: ['local-origin.dev', '*.local-origin.dev'],
    rewrites: async () => {
        return [
            {
                source: '/flask/:path*',
                destination:
                    process.env.NODE_ENV === 'development'
                        ? 'http://127.0.0.1:8011/api/:path*'
                        : '/api/',
            },
        ]
    },
};

export default nextConfig;
