/**
 * Where the Forensic Reports tile points.
 *
 * The Delay Analysis Toolkit is its own Streamlit application, not a COAir
 * screen. It runs as a separate container on this same host and the host nginx
 * serves it under /toolkit/ (deploy/nginx/coair-toolkit.conf), so the analyst
 * gets the toolkit exactly as its author built it — same theme, same charts,
 * same draft panels, same exports — without leaving the COAir origin.
 *
 * Relative on purpose: same origin means no build-time URL to configure, no
 * CORS, and no stale link when the deployment moves.
 */
export const TOOLKIT_URL = '/toolkit/';
