"""Utility functions for the RAG Chatbot."""
import os
from pathlib import Path
from typing import List, Tuple


def get_file_extension(filename: str) -> str:
    """Get lowercase file extension."""
    return Path(filename).suffix.lower()


def is_document_file(filename: str) -> bool:
    """Check if file is a supported document type."""
    return get_file_extension(filename) in {".pdf", ".docx", ".doc", ".txt"}


def is_data_file(filename: str) -> bool:
    """Check if file is a supported data type."""
    return get_file_extension(filename) in {".xlsx", ".xls", ".csv"}


def categorize_files(files: List[str]) -> Tuple[List[str], List[str]]:
    """Categorize files into documents and data files."""
    documents = [f for f in files if is_document_file(f)]
    data_files = [f for f in files if is_data_file(f)]
    return documents, data_files


def save_uploaded_file(uploaded_file, target_dir) -> str:
    """Save an uploaded file to target directory."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / uploaded_file.name
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(file_path)


def truncate_text(text: str, max_length: int = 500) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def format_file_size(size_bytes: int) -> str:
    """Format file size to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
