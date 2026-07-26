import { useCallback, useEffect, useState } from 'react';

/**
 * Drawing sheet <-> blueprint.
 *
 * Light is the drawing sheet (paper, ink lines) and the platform's
 * primary identity; dark is the blueprint (ink ground, white lines).
 * The choice is stored under the same `platform.sheet` key the portal
 * and the Delay Analysis Toolkit use, so flipping the mode in one
 * module flips it for the whole document set.
 *
 * With nothing stored, the OS preference decides — which is why the
 * attribute is only stamped once a mode has actually been chosen.
 */
export type SheetMode = 'light' | 'dark';

const STORE_KEY = 'platform.sheet';

/* Private browsing and blocked storage both throw here. */
function safeGet(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}

function safeSet(k: string, v: string): void {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* no-op */
  }
}

export function currentSheetMode(): SheetMode {
  const saved = safeGet(STORE_KEY);
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function useSheetMode() {
  const [mode, setMode] = useState<SheetMode>(currentSheetMode);

  useEffect(() => {
    document.documentElement.setAttribute('data-sheet', mode);
  }, [mode]);

  const toggle = useCallback(() => {
    setMode((prev) => {
      const next: SheetMode = prev === 'dark' ? 'light' : 'dark';
      safeSet(STORE_KEY, next);
      return next;
    });
  }, []);

  return { mode, toggle };
}
