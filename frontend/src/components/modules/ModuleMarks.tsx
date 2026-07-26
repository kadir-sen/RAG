/**
 * The three module marks, drawn in the platform's drafting language.
 *
 * Ported from delay-disputes-portal/assets/img/mark-*.svg, with one
 * deliberate change: the portal ships them as .svg files whose colours are
 * the light palette's hexes, hardcoded. An <img> cannot inherit a CSS
 * variable, so on the blueprint ground those files render as bright white
 * stickers on an ink page. Inlined here instead, every hex swapped for the
 * token it was standing in for, so a mark follows whichever sheet is up:
 *
 *   #FCFCFA → --paper     #14324A → --ink       #9B3227 → --red
 *   #EBF2F7 → --grid      #5B7994 → --ink-soft  #3F6B4F → --green
 *
 * Each is drawn on the same 256-square of paper with the same 32px grid, so
 * the three read as one set. They say what the module does, not what it is
 * called.
 */

interface MarkProps {
  className?: string;
}

/** The paper and its blue-line grid — the ground all three marks share. */
function Sheet() {
  return (
    <>
      <rect width="256" height="256" fill="var(--paper)" />
      <g stroke="var(--grid)" strokeWidth="1">
        <path d="M32 0V256M64 0V256M96 0V256M128 0V256M160 0V256M192 0V256M224 0V256" />
        <path d="M0 32H256M0 64H256M0 96H256M0 128H256M0 160H256M0 192H256M0 224H256" />
      </g>
    </>
  );
}

/** Chronology — a spine with entries hung off it; the contested one in red. */
export function ChronologyMark({ className = '' }: MarkProps) {
  return (
    <svg viewBox="0 0 256 256" className={className} role="img" aria-label="Chronology">
      <Sheet />
      {/* the spine: a chronology runs on one axis */}
      <path d="M76 36V220" stroke="var(--ink)" strokeWidth="3" strokeLinecap="square" />
      {/* entries: annotation rules of unequal weight, one per event */}
      <g strokeLinecap="square">
        <path d="M98 62H226" stroke="var(--ink-soft)" strokeWidth="7" />
        <path d="M98 100H194" stroke="var(--ink-soft)" strokeWidth="7" />
        <path d="M98 138H234" stroke="var(--red)" strokeWidth="7" />
        <path d="M98 176H182" stroke="var(--ink-soft)" strokeWidth="7" />
        <path d="M98 208H210" stroke="var(--ink-soft)" strokeWidth="7" />
      </g>
      {/* event nodes; the contested one is struck in revision red */}
      <g fill="var(--paper)" stroke="var(--ink)" strokeWidth="3">
        <circle cx="76" cy="62" r="8" />
        <circle cx="76" cy="100" r="8" />
        <circle cx="76" cy="176" r="8" />
        <circle cx="76" cy="208" r="8" />
      </g>
      <circle cx="76" cy="138" r="8" fill="var(--red)" stroke="var(--red)" strokeWidth="3" />
      {/* registration ticks, top and bottom of the axis */}
      <g stroke="var(--ink)" strokeWidth="3" strokeLinecap="square">
        <path d="M64 36H88" />
        <path d="M64 220H88" />
      </g>
    </svg>
  );
}

/** Reports — bars against a data date; the slipped one in red. */
export function ReportsMark({ className = '' }: MarkProps) {
  return (
    <svg viewBox="0 0 256 256" className={className} role="img" aria-label="Reports">
      <Sheet />
      {/* driving logic: finish-to-start ties, drawn before the bars */}
      <g stroke="var(--ink-soft)" strokeWidth="2" fill="none">
        <path d="M136 60H150V88" />
        <path d="M152 96H166V124" />
        <path d="M216 132H228V188" />
      </g>
      {/* the bars: baseline in ink, the slipped one in revision red */}
      <rect x="40" y="48" width="96" height="18" fill="var(--ink)" />
      <rect x="72" y="84" width="80" height="18" fill="var(--ink)" />
      <rect x="100" y="120" width="116" height="18" fill="var(--red)" />
      <rect x="56" y="156" width="68" height="18" fill="var(--ink-soft)" />
      <rect x="140" y="192" width="88" height="18" fill="var(--green)" />
      {/* data date */}
      <path d="M118 30V226" stroke="var(--ink)" strokeWidth="2" strokeDasharray="7 6" />
      <path d="M110 30H126" stroke="var(--ink)" strokeWidth="3" strokeLinecap="square" />
    </svg>
  );
}

/** Chatbot — a question still open, and the answer inked in and cited. */
export function ChatbotMark({ className = '' }: MarkProps) {
  return (
    <svg viewBox="0 0 256 256" className={className} role="img" aria-label="Chatbot">
      <Sheet />
      {/* the question: outlined, still open */}
      <path
        d="M28 44 H162 V114 H47 L28 133 Z"
        fill="var(--paper)"
        stroke="var(--ink)"
        strokeWidth="3"
        strokeLinejoin="miter"
      />
      <g fill="var(--ink-soft)">
        <rect x="46" y="64" width="94" height="8" />
        <rect x="46" y="80" width="102" height="8" />
        <rect x="46" y="96" width="58" height="8" />
      </g>
      {/* the answer: inked in, and cited */}
      <path d="M94 142 H228 V219 L209 200 H94 Z" fill="var(--ink)" />
      <rect x="112" y="160" width="94" height="8" fill="var(--paper)" />
      <rect x="112" y="176" width="54" height="8" fill="var(--paper)" />
      {/* source reference */}
      <rect x="174" y="176" width="30" height="8" fill="var(--red)" />
    </svg>
  );
}
