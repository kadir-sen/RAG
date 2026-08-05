import { useSheetMode } from '../../hooks/useSheetMode';

/**
 * Flips the whole UI between the drawing sheet (light) and the
 * blueprint (dark) — the same control, and the same wording, as the
 * platform portal's sheet toggle.
 */
export default function SheetToggle() {
  const { mode, toggle } = useSheetMode();
  return (
    <button
      type="button"
      onClick={toggle}
      className="sheet-toggle"
      aria-label="Switch between drawing sheet and blueprint"
      title="Switch between drawing sheet and blueprint"
    >
      <svg className="sheet-toggle-icon" aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <circle cx="12" cy="12" r="8" />
        <path d="M12 4a8 8 0 010 16z" fill="currentColor" stroke="none" />
      </svg>
      <span className="sheet-toggle-label">{mode === 'dark' ? 'Drawing sheet' : 'Blueprint'}</span>
    </button>
  );
}
