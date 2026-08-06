import { lazy, Suspense, useEffect, useRef } from 'react';
import { useUIStore } from '../../stores/uiStore';

const RightDocViewer = lazy(() => import('./RightDocViewer'));

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** A shared, responsive viewer surface for Chat, Chronology and reports. */
export default function DocumentViewerHost() {
  const open = useUIStore((state) => state.rightPanelOpen);
  const closeViewer = useUIStore((state) => state.closeViewer);
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const lastInteractionRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const rememberTrigger = (event: PointerEvent) => {
      const target = event.target instanceof Element
        ? event.target.closest<HTMLElement>('button, a[href], [role="button"]')
        : null;
      if (target && !panelRef.current?.contains(target)) lastInteractionRef.current = target;
    };
    document.addEventListener('pointerdown', rememberTrigger, true);
    return () => document.removeEventListener('pointerdown', rememberTrigger, true);
  }, []);

  useEffect(() => {
    if (!open) return;
    const active = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement
      : null;
    returnFocusRef.current = active ?? lastInteractionRef.current;
    const compact = window.matchMedia('(max-width: 1023px)').matches;
    const previousBodyOverflow = document.body.style.overflow;
    if (compact) document.body.style.overflow = 'hidden';

    const focusTimer = window.setTimeout(() => {
      panelRef.current?.querySelector<HTMLElement>('[data-viewer-close]')?.focus();
    }, 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeViewer();
        return;
      }
      if (event.key !== 'Tab' || !compact || !panelRef.current) return;
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      window.setTimeout(() => returnFocusRef.current?.focus(), 0);
    };
  }, [open, closeViewer]);

  if (!open) return null;
  const modal = window.matchMedia('(max-width: 1023px)').matches;

  return (
    <>
      <button
        type="button"
        aria-label="Close document viewer"
        onClick={closeViewer}
        className="fixed inset-0 z-[60] hidden bg-[var(--overlay)] md:block lg:hidden"
      />
      <div
        ref={panelRef}
        data-testid="document-viewer"
        role="dialog"
        aria-modal={modal ? 'true' : undefined}
        aria-label="Project document viewer"
        className="fixed inset-0 z-[70] h-dvh min-w-0 bg-[var(--bg-secondary)] md:left-auto md:w-[72vw] md:max-w-[640px] lg:relative lg:inset-auto lg:z-auto lg:h-full lg:w-[420px] lg:max-w-none lg:shrink-0"
      >
        <Suspense fallback={<div className="grid h-full place-items-center text-[11px] text-[var(--text-muted)]">Loading document…</div>}>
          <RightDocViewer />
        </Suspense>
      </div>
    </>
  );
}
