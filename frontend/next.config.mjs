/** @type {import('next').NextConfig} */
const isExport = process.env.NEXT_BUILD_MODE === 'export';
const distDir = isExport ? 'dist' : process.env.NEXT_DIST_DIR;

const nextConfig = {
  ...(distDir ? { distDir } : {}),
  ...(isExport
    ? { output: 'export' }
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
