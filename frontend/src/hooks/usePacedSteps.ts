import { useEffect, useRef, useState } from 'react';
import type { ActivityStep } from '../types/api';

/**
 * Reveal activity steps at a readable pace.
 *
 * The steps are real — they are published by the retrieval itself as it runs, so
 * each line names a document that was actually read. What they are not is
 * *slow*: the evidence build finishes in about three seconds on a warm index and
 * emits ~25 steps, which arrive in two or three polls. Painting 25 lines in
 * 400 ms is not a progress display, it is a flicker.
 *
 * So the reveal is paced. This is a presentation concern and it is kept honest
 * two ways: nothing is invented — a step is only ever shown once the server has
 * reported it — and the finished report prints the true elapsed time and pass
 * count, so the document never inherits the pacing.
 */
export function usePacedSteps(
  steps: ActivityStep[] | undefined,
  opts: { msPerStep?: number; active: boolean },
) {
  const { msPerStep = 620, active } = opts;
  const [shown, setShown] = useState(0);
  const timer = useRef<number | null>(null);

  // A new run starts the reveal over.
  useEffect(() => {
    if (active) setShown(0);
  }, [active]);

  useEffect(() => {
    const available = steps?.length ?? 0;
    if (!active || shown >= available) return;
    timer.current = window.setTimeout(() => setShown((n) => n + 1), msPerStep);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [active, shown, steps?.length, msPerStep]);

  const available = steps?.length ?? 0;
  return {
    visible: (steps ?? []).slice(0, shown),
    /** Every step the server reported has now been shown. */
    caughtUp: shown >= available && available > 0,
    shown,
    available,
  };
}
