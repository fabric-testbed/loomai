/**
 * Build a WebSocket URL for the given path.
 *
 * In development (`next dev` on :3000), WebSocket upgrade requests can't be
 * proxied by Next.js rewrites, so we connect directly to the FastAPI backend
 * on :8000.
 *
 * In production (behind nginx) we use the page's own host, since nginx handles
 * the WebSocket proxy at `/ws/`. This must include the case where the built
 * container is run locally (e.g. `docker compose up` on Windows), where the
 * browser hits nginx at `localhost:3000` but no backend is exposed on :8000 —
 * so we gate the dev branch on the build-time `NODE_ENV`, which Next replaces
 * with `'production'` in the exported bundle, rather than the runtime host/port
 * alone.
 */
export function buildWsUrl(path: string): string {
  const isDev =
    process.env.NODE_ENV !== 'production' &&
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') &&
    window.location.port === '3000';

  if (isDev) {
    return `ws://${window.location.hostname}:8000${path}`;
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const basePath = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH) || '';
  return `${protocol}//${window.location.host}${basePath}${path}`;
}
