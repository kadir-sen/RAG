# Agentic RAG Chatbot

A hybrid Retrieval-Augmented Generation chatbot that intelligently handles both **unstructured documents** (PDFs, Word, text) and **structured data** (Excel, CSV) with a modern ChatGPT-like interface.

## Features

- **Document RAG**: Semantic search across PDFs, DOCX, TXT with page-level citations
- **SQL Data Analysis**: Safe query execution using DuckDB (no arbitrary code execution)
- **Smart Routing**: Automatic classification of queries (Document/Data/Hybrid/Timeline) with Turkish + English support
- **Table Extraction**: Automatic extraction of tables from Excel and PDF files stored as Parquet
- **Notice Extraction**: Structured metadata extraction from documents (sender, recipient, date, references)
- **Light Graph**: Document-level relationship graph for timeline and correspondence queries
- **Modern UI**: Clean, minimal ChatGPT-inspired interface
- **Source Citations**: View exact pages and highlighted text for document sources

## Architecture

```
User Query → Router (LLM classification) → Document RAG (Pinecone)
                                        → SQL Analyzer (DuckDB + Parquet views)
                                        → Timeline (Light Graph)
                                        → Hybrid (both + synthesis)
            ↓
        Response with Sources + Evidence
```

### Phase 2: Notice + Light Graph

The system includes a lightweight document-level graph layer for timeline and correspondence queries:

```
Document Upload → Parse Text → Extract Notice Metadata → Build Graph Edges
                                     ↓
                              {date, sender, recipient, subject, refs}
                                     ↓
                              Edges: references, same_party, chronological
```

**Why Light Graph instead of Deep GraphRAG?**
- GraphRAG is powerful but heavy (expensive LLM calls, complex infrastructure)
- Our approach: regex-first extraction + document-level relationships
- Sufficient for timeline queries, correspondence chains, "who sent what when"
- Every extracted field has evidence spans for debuggability

## Tech Stack

- **Framework**: LlamaIndex
- **LLM**: Google Gemini
- **Vector DB**: Pinecone (serverless)
- **SQL Engine**: DuckDB (safe, no arbitrary code execution)
- **UI**: Streamlit
- **Document Parsing**: PyMuPDF, python-docx

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Copy `.env.example` to `.env` and add your keys:

```bash
cp .env.example .env
```

Edit `.env`:
```
GOOGLE_API_KEY=your_google_api_key_here
PINECONE_API_KEY=your_pinecone_api_key_here
```

Get your keys:
- Google: https://aistudio.google.com/app/apikey
- Pinecone: https://app.pinecone.io/

### 3. Run the Application

```bash
streamlit run app.py
```

Open http://localhost:8501

## Project Structure

```
ML_project/
├── app.py                      # Streamlit UI
├── src/
│   ├── config.py               # Configuration & API keys
│   ├── document_rag.py         # PDF/DOCX indexing with Pinecone
│   ├── data_analyzer_sql.py    # SQL-based data analysis (DuckDB + Parquet)
│   ├── router.py               # Query classification & routing
│   ├── logger.py               # Structured logging
│   ├── ocr_pipeline.py         # OCR for scanned PDFs
│   ├── catalog.py              # Metadata catalog for tables/notices
│   ├── table_ingestion.py      # Unified ingestion pipeline
│   ├── excel_table_extractor.py # Excel table detection
│   ├── pdf_table_extractor.py  # PDF table extraction
│   ├── ocr_detector.py         # OCR decision classifier
│   ├── notice_extractor.py     # Notice metadata extraction (Phase 2)
│   ├── light_graph.py          # Document relationship graph (Phase 2)
│   └── utils.py                # Utility functions
├── data/
│   ├── documents/              # Uploaded documents
│   ├── tables/                 # Uploaded data files
│   ├── notices/                # Extracted notice JSON files
│   └── graph/                  # Document graph storage
├── storage/
│   └── parquet/                # Extracted tables as Parquet
├── tests/                      # Unit tests
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## Usage

### Upload Files

1. Use the sidebar to upload documents (PDF, DOCX, TXT) or data files (Excel, CSV)
2. Files are automatically processed and indexed
3. Click "Load Project Files" to load files from project folders

### Ask Questions

**Document Questions:**
```
What are the payment terms in the contract?
Summarize the weekly progress report
What liabilities are mentioned in section 5?
Sözleşmedeki yükümlülükler nelerdir?  (Turkish)
```

**Data Questions:**
```
Calculate the total by category
What is the average completion rate?
Show top 10 items by value
Aylık ortalama nedir?  (Turkish)
```

**Hybrid Questions:**
```
Compare the contract terms with the actual progress data
What discrepancies exist between reported and actual figures?
```

## Security

- **No arbitrary code execution**: Data queries use SQL (DuckDB) with strict validation
- **SELECT-only**: Only read operations allowed on data
- **No DDL/DML**: DROP, INSERT, UPDATE, DELETE, CREATE are blocked
- **Result limits**: Max 200 rows returned per query

## Key Improvements Over Basic RAG

1. **Page-level citations**: Each PDF page stored separately with metadata (no regex guessing)
2. **Deduplication**: Namespace-based indexing prevents duplicate vectors
3. **Safe SQL**: DuckDB replaces unsafe LLM-generated Python execution
4. **Multilingual routing**: English + Turkish keyword support
5. **Clean UI**: Modern ChatGPT-like interface

## Example Queries

### Document Query
```
Q: What are the liability terms?
→ Routes to Document RAG
→ Returns answer with page citations
→ Shows: "Sample Contract.pdf, Page 5, Score: 0.89"
```

### Data Query
```
Q: Calculate average progress by week
→ Routes to SQL Analyzer
→ Generates: SELECT week, AVG(progress) FROM data GROUP BY week
→ Returns table + summary
```

### Hybrid Query
```
Q: Compare contract deadlines with actual completion dates
→ Routes to BOTH handlers
→ Synthesizes document context + data analysis
→ Returns combined answer with sources from both
```

### Timeline Query (Phase 2)
```
Q: Show me the timeline of all notices
→ Routes to Light Graph
→ Returns chronological list of documents with metadata

Q: What delay notices were sent?
→ Searches notices by action keyword
→ Returns documents mentioning "delay" with evidence

Q: Who replied to whom about the extension request?
→ Traces document chain by references
→ Shows correspondence flow with dates
```

## Troubleshooting

**API Key errors:**
- Ensure `.env` file exists in project root
- Check keys are valid and not expired

**Pinecone errors:**
- Verify Pinecone key and index name
- Check region matches (default: us-east-1)

**Import errors:**
- Run `pip install -r requirements.txt`
- For PyMuPDF: `pip install pymupdf`

## License

MIT
