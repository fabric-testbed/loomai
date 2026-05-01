/**
 * Prefix a static asset path with the base path for K8s sub-path deployments.
 * In standalone mode, returns the path unchanged.
 */
export function assetUrl(path: string): string {
  const basePath = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH) || '';
  return `${basePath}${path}`;
}
