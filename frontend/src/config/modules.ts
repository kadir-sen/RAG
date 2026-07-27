/**
 * Where the module tiles point.
 *
 * The Delay Analysis Toolkit is a separate Streamlit deployment rather than
 * part of this app. Its engines were vendored into COAir once and removed
 * again with the reporting rollback, so linking to the live app is what keeps
 * the two in step for now: there is no copy here to drift.
 *
 * Kept out of the component because this is the value most likely to change —
 * a redeploy of the toolkit gives it a new URL.
 */
export const TOOLKIT_URL =
  'https://delay-analysis-toolkit-zfrgfylt3zycrlzjvkmiug.streamlit.app/';
