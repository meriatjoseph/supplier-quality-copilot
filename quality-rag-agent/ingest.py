"""
Chunking / ingestion for the Customer Quality RAG Agent.

Chunking strategy
------------------
1. Each controlled document uses Markdown headers (`#` document title,
   `##` section headings) as its natural structure. We first split on
   headers with LangChain's MarkdownHeaderTextSplitter so every chunk keeps
   a `document` (filename-derived title) and `section` (nearest `##`
   heading) in its metadata -- this is what lets /retrieve cite
   "document name + section reference" rather than an opaque chunk id.
2. Header-defined sections in these documents run a few hundred words, so
   we then pass each header-split section through a
   RecursiveCharacterTextSplitter (chunk_size=800 chars, chunk_overlap=120
   chars) to keep individual chunks small enough for focused retrieval
   while preserving surrounding context via the overlap. Most sections fit
   in a single chunk; only the longer ones (e.g. the PFMEA sections) get
   split further, and each split child inherits the parent's
   document/section metadata.
3. Metadata schema per chunk: {document: str, section: str, source_file: str}.

Retrieval approach
-------------------
FAISS with cosine-similarity-style scoring (embeddings are normalized where
the provider supports it; MockEmbeddings normalizes explicitly). We
retrieve top_k=4 by default and compute a 0-1 confidence score from FAISS
L2 distance; below a threshold we return "no supporting evidence found"
rather than asserting a weak match, per the take-home's evidence-fidelity
requirement.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.llm import MockEmbeddings, get_embeddings_with_fallback  # noqa: E402

DOCS_DIR = Path(os.environ.get("DOCS_DIR", Path(__file__).resolve().parent.parent / "data" / "docs"))
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

HEADER_SPLITS = [("#", "document"), ("##", "section")]


def load_and_chunk_documents(docs_dir: Path = DOCS_DIR) -> list:
    from langchain_core.documents import Document

    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADER_SPLITS, strip_headers=False)
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, separators=["\n\n", "\n", ". ", " "]
    )

    all_chunks: list[Document] = []
    for path in sorted(docs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        header_docs = header_splitter.split_text(text)
        for hd in header_docs:
            document_title = hd.metadata.get("document", path.stem)
            section_title = hd.metadata.get("section", "General")
            sub_chunks = char_splitter.split_text(hd.page_content)
            for sub in sub_chunks:
                all_chunks.append(
                    Document(
                        page_content=sub,
                        metadata={
                            "document": document_title.strip(),
                            "section": section_title.strip(),
                            "source_file": path.name,
                        },
                    )
                )
    return all_chunks


def build_vectorstore(docs_dir: Path = DOCS_DIR) -> tuple[FAISS, bool]:
    """Returns (vectorstore, used_mock_embeddings). The caller needs to know
    which embedder was actually used because mock (hashed bag-of-words) and
    real provider embeddings produce relevance scores on different scales --
    see app.py's provider-aware RELEVANCE_FLOOR."""
    chunks = load_and_chunk_documents(docs_dir)
    embeddings = get_embeddings_with_fallback()
    try:
        return FAISS.from_documents(chunks, embeddings), isinstance(embeddings, MockEmbeddings)
    except Exception as exc:  # noqa: BLE001
        # Configured provider key present but rejected/unreachable at call time
        # (invalid key, quota, network). Fall back to the offline mock embedder
        # so the RAG agent stays usable rather than failing to start.
        print(f"WARNING: embeddings provider failed ({exc}); falling back to MockEmbeddings", file=sys.stderr)
        return FAISS.from_documents(chunks, MockEmbeddings()), True


if __name__ == "__main__":
    vs, used_mock = build_vectorstore()
    print(f"Built vectorstore with {vs.index.ntotal} chunks from {DOCS_DIR} (used_mock_embeddings={used_mock})")
