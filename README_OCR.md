# OCR Support for Agentic RAG Chatbot

This document describes the OCR (Optical Character Recognition) capability added to handle scanned PDFs and image-based documents.

## Overview

The OCR layer automatically detects and processes scanned PDF pages that don't have extractable text. It uses Tesseract OCR engine with support for English and Turkish languages.

## OCR Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `auto` (default) | Only OCR pages that need it | Mixed documents (some scanned, some digital) |
| `force` | OCR all pages regardless of text | When native extraction is unreliable |
| `off` | No OCR, text extraction only | Digital-only PDFs, faster processing |

## How It Works

### Auto Detection

In `auto` mode, each page is analyzed using fast heuristics:

1. **Character count check**: If extracted text has < 30 characters → OCR
2. **Alpha ratio check**: If letter ratio < 20% → OCR (catches garbled text)
3. **Image coverage check**: If page is 70%+ images with little text → OCR

### Extraction Flow

```
PDF Page
    │
    ▼
┌─────────────────────┐
│ Native text extract │ (PyMuPDF)
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ Quality check       │
│ - char_count        │
│ - alpha_ratio       │
│ - image_coverage    │
└─────────────────────┘
    │
    ├─── Good quality ──→ Use native text
    │
    └─── Poor quality ──→ OCR fallback
                              │
                              ▼
                         ┌─────────────────────┐
                         │ Render page to      │
                         │ 200 DPI image       │
                         └─────────────────────┘
                              │
                              ▼
                         ┌─────────────────────┐
                         │ Tesseract OCR       │
                         │ (eng or eng+tur)    │
                         └─────────────────────┘
                              │
                              ▼
                         Use OCR text
```

## Configuration

### Environment Variables

Add to your `.env` file:

```env
# OCR Settings
OCR_MODE=auto          # auto | force | off
OCR_ENGINE=tesseract   # tesseract (default)
OCR_LANG=eng           # eng | eng+tur | tur
OCR_DPI=200            # Image rendering DPI (higher = better but slower)
OCR_MAX_PAGES=500      # Safety limit per document

# Detection Thresholds
OCR_MIN_CHARS=30       # Min chars to skip OCR
OCR_MIN_ALPHA_RATIO=0.2
OCR_IMAGE_COVERAGE=0.7
```

### UI Settings

In the Streamlit sidebar:
- **OCR Mode**: Select Auto / Force / Off
- **OCR Language**: Select English / English+Turkish / Turkish

## Enabling Turkish OCR

### Docker (Recommended)

Turkish language pack is pre-installed in the Docker image:

```dockerfile
RUN apt-get install -y tesseract-ocr-tur
```

### Local Installation (Windows)

1. Download Tesseract installer from: https://github.com/UB-Mannheim/tesseract/wiki
2. During installation, select "Turkish" language data
3. Or download `tur.traineddata` from: https://github.com/tesseract-ocr/tessdata
4. Place in `C:\Program Files\Tesseract-OCR\tessdata\`

### Local Installation (Linux/Mac)

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr-tur

# macOS
brew install tesseract-lang
```

## Caching

OCR results are cached to avoid re-processing:

- **Location**: `.cache/ocr/` directory
- **Key**: Hash of (file_hash + page_number + dpi + language + engine)
- **Format**: JSON files

To clear cache:
```bash
rm -rf .cache/ocr/*
```

## Metadata

Each page document includes extraction metadata:

```python
{
    "file_name": "document.pdf",
    "page_number": 5,
    "extraction_method": "ocr",      # "native" | "ocr" | "native+ocr"
    "ocr_engine": "tesseract",       # Only if OCR used
    "ocr_language": "eng+tur",       # Only if OCR used
    "ocr_confidence": 0.85,          # Only if OCR used (0-1 scale)
    "table_hint": true,              # If table-like content detected
}
```

## Performance Considerations

### Speed

| Mode | Speed | Accuracy |
|------|-------|----------|
| `off` | Fastest | Native text only |
| `auto` | Fast for digital, slow for scanned | Best balance |
| `force` | Slowest | Most consistent |

### Tips

1. **Use `auto` mode** for mixed documents
2. **Increase DPI** (300) for low-quality scans at cost of speed
3. **Enable caching** - subsequent runs will be fast
4. **Limit pages** with `OCR_MAX_PAGES` for large documents

### Memory Usage

- OCR requires rendering pages to images
- ~10-20 MB per page at 200 DPI
- Consider batch processing for very large documents

## Troubleshooting

### "OCR not available" Warning

```
pytesseract not installed
```

**Fix**: Install dependencies:
```bash
pip install pytesseract Pillow
```

And install Tesseract OCR binary (see installation section).

### Low OCR Confidence

If confidence < 0.5, you'll see warnings in logs:
```
[OCR] Page 5: Low confidence: 0.42
```

**Possible causes**:
- Very low image quality
- Unusual fonts
- Skewed/rotated pages
- Mixed languages

**Fixes**:
- Increase DPI to 300
- Use `eng+tur` for mixed documents
- Pre-process PDFs to improve image quality

### Turkish Characters Not Recognized

```
Language eng+tur failed, using eng
```

**Fix**: Install Turkish language pack (see "Enabling Turkish OCR")

### Empty Pages After OCR

If pages still show as empty after OCR:
- Document may be image-only with no text
- PDF might be encrypted or have security restrictions
- Image quality may be too low

## Testing

### Smoke Test

Run the smoke test script:

```bash
python scripts/ocr_smoke_test.py document.pdf
python scripts/ocr_smoke_test.py scanned.pdf --mode force --lang eng+tur
```

### Unit Tests

```bash
pytest tests/test_ocr_pipeline.py -v
```

## Architecture

```
src/
├── ocr_pipeline.py      # OCR extraction module
│   ├── OCRResult        # Data class for OCR output
│   ├── PageText         # Data class for page extraction
│   ├── OCRCache         # File-based result caching
│   └── OCRPipeline      # Main OCR processor
│
├── document_rag.py      # Integration point
│   └── parse_pdf_by_pages()  # Uses OCRPipeline
│
└── config.py            # OCR configuration
    └── OCR_* settings
```

## Security Notes

- OCR processes images locally (no external API calls)
- Sensitive data in scanned documents will be extracted to text
- Logger includes redaction for common sensitive patterns (cards, phones, OTP)
- Cache files contain extracted text - secure appropriately
