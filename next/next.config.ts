import type { NextConfig } from "next";


const nextConfig: NextConfig = {
    /* config options here */
    // allowedDevOrigins: ['local-origin.dev', '*.local-origin.dev'],
    allowedDevOrigins: [
        'http://localhost:8010',
        'http://127.0.0.1:8010',
        'http://172.18.27.154:8010',
        'http://192.168.169.1:8010',
        'http://192.168.5.54:8010',
        'http://192.168.5.32:8010',
        'http://192.168.137.1:8010',
        'http://local-origin.dev',
        'http://*.local-origin.dev'
    ],
    rewrites: async () => {
        return [
            // {
            //     source: '/flask/:path*',
            //     destination: '/api/proxy/:path*',
            // },
            {
                source: '/flask/:path*',
                destination:
                    process.env.NODE_ENV === 'development'
                        ? 'http://127.0.0.1:8011/api/:path*'
                        // ? 'http://host.docker.internal:8011/api/:path*'
                        : '/api/',
            },
        ]
    },
};

export default nextConfig;
