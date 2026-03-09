/** @type {import('next').NextConfig} */
const isExport = process.env.NEXT_BUILD_MODE === 'export';

const nextConfig = {
  ...(isExport
    ? { output: 'export', distDir: 'dist' }
    : {
        // In dev mode, proxy /api/* to the FastAPI backend
        async rewrites() {
          return [
            {
              source: '/api/:path*',
              destination: 'http://localhost:8000/api/:path*',
            },
          ];
        },
      }),
};

export default nextConfig;
