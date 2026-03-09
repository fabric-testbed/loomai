/**
 * Build a WebSocket URL for the given path.
 *
 * In development (Next.js dev server on :3000), WebSocket upgrade requests
 * can't be proxied by Next.js rewrites, so we connect directly to the
 * FastAPI backend on :8000.
 *
 * In production (behind nginx), we use the page's own host since nginx
 * handles the WebSocket proxy.
 */
export function buildWsUrl(path: string): string {
  const isDev =
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') &&
    window.location.port === '3000';

  if (isDev) {
    return `ws://${window.location.hostname}:8000${path}`;
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}
