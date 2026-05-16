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
  newChatButton: 'button:has-text("Yeni sohbet")',
  recentChats: '.truncate',
  addFilesButton: 'button:has-text("Add Files")',
  uploadingButton: 'button:has-text("Uploading...")',
  exportLink: '[aria-label="Export file list as CSV"]',
  fileInput: 'input[type="file"]',
  renameButton: '[title="Rename"]',
  deleteButton: '[title="Delete"]',
  sidebarChatsHeading: 'p:has-text("Sohbetler")',

  // ── Sidebar primary action buttons (the five "big" rows) ───
  sidebarNewChat: 'button:has-text("Yeni sohbet")',
  sidebarSearchChats: 'button:has-text("Sohbetlerde ara")',

  // ── Sidebar Folders (Documents / Correspondence / Spreadsheet) ──
  folderDocuments: 'button[aria-expanded]:has-text("Documents")',
  folderCorrespondence: 'button[aria-expanded]:has-text("Correspondence")',
  folderSpreadsheet: 'button[aria-expanded]:has-text("Spreadsheet")',
  folderHeader: (name: string) =>
    `button[aria-expanded]:has-text("${name}")`,

  // ── Chat Action Chips ──────────────────────────────────
  actionChipsStrip: 'div:has(> span:has-text("Programs"))',
  chipCorrespondence: 'button[aria-pressed]:has-text("Correspondence")',
  chipDocumentAnalysis: 'button[aria-pressed]:has-text("Document Analysis")',
  chipByLabel: (label: string) =>
    `button[aria-pressed]:has-text("${label}")`,

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
