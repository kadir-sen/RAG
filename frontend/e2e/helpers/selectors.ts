/**
 * Centralized selector map for all interactive UI elements.
 * Priority: #id > aria-label > role > text > CSS
 */
export const S = {
  // ── TopNav ─────────────────────────────────────────────
  sidebarToggle: '[aria-label="Close sidebar"], [aria-label="Open sidebar"]',
  sidebarOpen: '[aria-label="Close sidebar"]',
  sidebarClosed: '[aria-label="Open sidebar"]',
  settingsButton: '[aria-label="Open settings"]',
  userAvatar: '[aria-label="User avatar"]',
  branding: '[aria-label="COAir"]',

  // ── Chat Input ─────────────────────────────────────────
  chatInput: '#chat-input',
  sendButton: '[aria-label="Send message"]',

  // ── Chat Stream ────────────────────────────────────────
  chatLog: '[role="log"]',
  typingIndicator: '[role="status"]',
  assistantMessage: '.prose',
  userMessage: '.bg-\\[var\\(--accent\\)\\]',

  // ── Welcome Screen ─────────────────────────────────────
  welcomeHeading: 'h1',
  correspondenceCard: 'button:has-text("Correspondence"):has-text("MODE.01")',
  documentAnalysisCard: 'button:has-text("Document Analysis"):has-text("MODE.02")',

  // ── Sidebar ────────────────────────────────────────────
  sidebar: '[aria-label="Sidebar"]',
  newChatButton: 'button:has-text("New Chat")',
  recentChats: '.truncate',
  addFilesButton: 'button:has-text("Add Files")',
  uploadingButton: 'button:has-text("Uploading...")',
  exportLink: '[aria-label="Export file list as CSV"]',
  fileInput: 'input[type="file"]',
  renameButton: '[title="Rename"]',
  deleteButton: '[title="Delete"]',
  sidebarChatsHeading: 'p:has-text("Recent Queries")',

  // ── Sidebar primary action buttons (Knowledge Base section) ───
  sidebarNewChat: 'button:has-text("AI Assistant")',
  sidebarSearchChats: 'button[aria-label="Search recent queries"], button[aria-label="Close search"]',

  // ── Sidebar Folders (Documents / Communications / Spreadsheets) ──
  folderDocuments: 'button[aria-expanded]:has-text("Documents")',
  folderCorrespondence: 'button[aria-expanded]:has-text("Communications")',
  folderSpreadsheet: 'button[aria-expanded]:has-text("Spreadsheets")',
  folderHeader: (name: string) =>
    `button[aria-expanded]:has-text("${name}")`,

  // ── Mode toggle (moved into sidebar; chat thread is clean) ───
  modeToggle: '[data-testid="sidebar-mode-toggle"]',
  chipCorrespondence: '[data-testid="sidebar-mode-toggle"] [data-mode="correspondence"]',
  chipDocumentAnalysis: '[data-testid="sidebar-mode-toggle"] [data-mode="document_analysis"]',
  chipByLabel: (label: string) =>
    `[data-testid="sidebar-mode-toggle"] button:has-text("${label}")`,
  // Legacy alias (deprecated; kept so the action-chips spec can still target a strip)
  actionChipsStrip: '[data-testid="sidebar-mode-toggle"]',

  // ── Usage Badge ────────────────────────────────────────
  usageBadge: '[aria-label="Usage budget"]',

  // ── Correspondence Mode ────────────────────────────────
  emailCheckbox: 'input[type="checkbox"]',
  quickPrompt: (label: string) => `button:has-text("${label}")`,

  // ── Settings Modal ─────────────────────────────────────
  settingsDialog: '[role="dialog"]',
  settingsTitle: '#settings-title',
  settingsClose: '[aria-label="Close settings"]',
  settingsBackdrop: '[role="presentation"]',

  // ── Document Viewer ────────────────────────────────────
  viewerClose: '[aria-label="Close viewer"]',
  prevPage: '[aria-label="Previous page"]',
  nextPage: '[aria-label="Next page"]',
  viewerExport: 'button:has-text("Export")',

  // ── Chat Page ──────────────────────────────────────────
  backButton: '[aria-label="Back to mode selection"]',
  mainContent: '#main-content',

  // ── Copy Button ────────────────────────────────────────
  copyButton: '[aria-label="Copy response"]',
} as const;
