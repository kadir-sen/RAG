import { useCallback, useRef } from 'react';
import ModuleTile from '../components/modules/ModuleTile';
import { ChatbotMark, ChronologyMark, ReportsMark } from '../components/modules/ModuleMarks';

/**
 * What you land on after signing in.
 *
 * Signing in used to drop you straight into the chatbot, which made the
 * chatbot look like the whole product and buried everything else inside it as
 * a "skill". The three capabilities are peers, so they are presented as peers:
 * pick where you are working, then that module's own layers open.
 *
 * Reports is drawn but inert until it has something behind it — showing it
 * greyed is more honest than hiding it, and it sets the expectation that the
 * set is three.
 */

const MARK_CLASS = 'w-full h-full block';

export default function ModulePickerPage() {
  const gridRef = useRef<HTMLUListElement>(null);

  /* Left/right walk the tiles, the way the portal's picker does. Only the
     enabled ones are reachable — a disabled tile is not a link. */
  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const links = Array.from(
      gridRef.current?.querySelectorAll<HTMLAnchorElement>('a[data-module]') ?? [],
    );
    if (links.length < 2) return;
    const here = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (here === -1) return;
    e.preventDefault();
    const step = e.key === 'ArrowRight' ? 1 : -1;
    links[(here + step + links.length) % links.length].focus();
  }, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-12 md:py-16">
        <header className="mb-10">
          <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
            Select · module
          </p>
          <h1 className="mt-2 text-2xl md:text-3xl font-semibold tracking-tight text-[var(--text-primary)]">
            Where are you working?
          </h1>
          <p className="mt-2 text-[13px] text-[var(--text-secondary)] max-w-xl">
            Three ways into the same project record. The one you pick opens with
            your session intact.
          </p>
        </header>

        <ul
          ref={gridRef}
          onKeyDown={onKeyDown}
          className="grid gap-6 md:gap-8 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 list-none p-0"
        >
          <li>
            <ModuleTile
              index="01"
              name="Chatbot"
              role="Ask · cite · verify"
              blurb="Interrogate the record in plain language. Every answer comes back cited to its source document."
              mark={<ChatbotMark className={MARK_CLASS} />}
              to="/chat"
            />
          </li>
          <li>
            <ModuleTile
              index="02"
              name="Chronology"
              role="Event timeline"
              blurb="Follow what happened and when, drawn straight from the project record. Filter by event, party or period."
              mark={<ChronologyMark className={MARK_CLASS} />}
              to="/chronology"
            />
          </li>
          <li>
            <ModuleTile
              index="03"
              name="Forensic Reports"
              role="Delay Analysis Toolkit"
              blurb="Programme forensics — DCMA checks, variance and critical path. Opens the toolkit, a separate application."
              mark={<ReportsMark className={MARK_CLASS} />}
              to="/forensic"
            />
          </li>
        </ul>
      </div>
    </div>
  );
}
