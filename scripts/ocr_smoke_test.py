#!/usr/bin/env python3
"""
OCR Smoke Test Script

Tests the OCR pipeline on a PDF file and prints extraction results.

Usage:
    python scripts/ocr_smoke_test.py <pdf_path> [--mode auto|force|off] [--lang eng|eng+tur]

Examples:
    python scripts/ocr_smoke_test.py document.pdf
    python scripts/ocr_smoke_test.py scanned.pdf --mode force --lang eng+tur
"""
import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ocr_pipeline import get_ocr_pipeline, OCRPipeline


def run_smoke_test(pdf_path: str, mode: str = "auto", language: str = "eng"):
    """Run OCR smoke test on a PDF file."""
    path = Path(pdf_path)

    if not path.exists():
        print(f"ERROR: File not found: {pdf_path}")
        return False

    if not path.suffix.lower() == ".pdf":
        print(f"ERROR: Not a PDF file: {pdf_path}")
        return False

    print("=" * 60)
    print(f"OCR SMOKE TEST")
    print("=" * 60)
    print(f"File: {path.name}")
    print(f"Size: {path.stat().st_size / 1024:.1f} KB")
    print(f"Mode: {mode}")
    print(f"Language: {language}")
    print("=" * 60)

    # Initialize OCR pipeline
    ocr = OCRPipeline(mode=mode, language=language)
    print(f"\nOCR Engine: {ocr.engine}")
    print(f"DPI: {ocr.dpi}")
    print(f"Max pages: {ocr.max_pages}")

    # Extract text
    print("\n" + "-" * 60)
    print("EXTRACTION RESULTS")
    print("-" * 60)

    results = ocr.extract_text_auto(str(pdf_path))

    # Summary stats
    native_count = sum(1 for r in results if r.extraction_method == "native")
    ocr_count = sum(1 for r in results if r.extraction_method in ("ocr", "native+ocr"))
    failed_count = sum(1 for r in results if r.char_count < 10)
    total_chars = sum(r.char_count for r in results)

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"Total pages: {len(results)}")
    print(f"Native extraction: {native_count}")
    print(f"OCR extraction: {ocr_count}")
    print(f"Failed/empty: {failed_count}")
    print(f"Total characters: {total_chars:,}")

    # Print first 200 chars of each page
    print(f"\n{'=' * 60}")
    print("PAGE CONTENT PREVIEW (first 200 chars)")
    print("=" * 60)

    for page_result in results:
        page_num = page_result.page_number
        method = page_result.extraction_method
        chars = page_result.char_count
        conf = page_result.ocr_confidence

        conf_str = f", conf={conf:.2f}" if conf else ""
        print(f"\n[PAGE {page_num}] method={method}, chars={chars}{conf_str}")

        if page_result.text:
            preview = page_result.text[:200].replace('\n', ' ')
            print(f"  Preview: {preview}...")
        else:
            print("  Preview: (empty)")

        if page_result.warnings:
            for w in page_result.warnings:
                print(f"  WARNING: {w}")

    print("\n" + "=" * 60)
    print("SMOKE TEST COMPLETE")
    print("=" * 60)

    return True


def main():
    parser = argparse.ArgumentParser(description="OCR Smoke Test for PDF files")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument("--mode", choices=["auto", "force", "off"], default="auto",
                        help="OCR mode (default: auto)")
    parser.add_argument("--lang", default="eng",
                        help="OCR language (default: eng, options: eng, eng+tur, tur)")

    args = parser.parse_args()

    success = run_smoke_test(args.pdf_path, args.mode, args.lang)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
