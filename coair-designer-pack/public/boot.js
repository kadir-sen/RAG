/* Sets the sheet mode before first paint so the app never flashes the
   wrong ground. Kept as its own file (rather than an inline <script>)
   so the deployed Content-Security-Policy can refuse inline scripts —
   the same arrangement the platform portal uses. Must load
   synchronously in <head>. useSheetMode() owns it from then on. */
(function () {
  try {
    var m = localStorage.getItem('platform.sheet');
    if (m === 'light' || m === 'dark') {
      document.documentElement.setAttribute('data-sheet', m);
    }
  } catch (e) { /* storage blocked — fall through to the media query */ }
})();
