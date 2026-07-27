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
      {mode === 'dark' ? 'Drawing sheet' : 'Blueprint'}
    </button>
  );
}
