import { useState } from 'react';

/**
 * "download · word" — the chronology's way out of the browser.
 *
 * Drawn as the sheet's other inline actions are (mono, tracked-out, muted until
 * hovered) rather than as a filled button: this sits in a header beside "← all
 * events" and should read as the same kind of thing.
 *
 * It owns its own pending and error state because the download is a blob fetch
 * that can take a second on a long chronology, and a button that looks inert
 * while it works invites a second click and a second file.
 */
interface Props {
  onDownload: () => Promise<void>;
  label?: string;
}

export default function DownloadDocxButton({ onDownload, label = 'download · word' }: Props) {
  const [state, setState] = useState<'idle' | 'working' | 'failed'>('idle');

  const run = async () => {
    if (state === 'working') return;
    setState('working');
    try {
      await onDownload();
      setState('idle');
    } catch {
      // Say so rather than failing silently — nothing appears in the downloads
      // tray either way, so a silent failure looks like the click was missed.
      setState('failed');
      setTimeout(() => setState('idle'), 4000);
    }
  };

  return (
    <button
      type="button"
      onClick={run}
      disabled={state === 'working'}
      aria-live="polite"
      className={`shrink-0 font-mono text-[10px] tracking-[0.18em] uppercase transition-colors no-underline ${
        state === 'failed'
          ? 'text-[var(--danger)]'
          : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
      } disabled:opacity-60 disabled:cursor-wait`}
    >
      {state === 'working' ? 'preparing…' : state === 'failed' ? 'download failed' : label}
    </button>
  );
}
