"""
Swappable LLM/embeddings provider factory.

Provider is selected via the LLM_PROVIDER env var (default "google", since
this environment ships a GOOGLE_API_KEY). Supported: "google", "openai",
"anthropic", "mock". "mock" requires no API key and is used as an automatic
fallback if the configured provider's key is missing, so the system never
hard-fails just because a key isn't set.

Swap providers by setting LLM_PROVIDER (+ the matching *_API_KEY / *_MODEL
env vars) in docker-compose.yml or the shell environment -- no code changes.
"""
from __future__ import annotations

import os


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "google").lower()


def get_chat_model(temperature: float = 0.0):
    """Returns a LangChain chat model instance, or None if only mock mode is available."""
    provider = _provider()

    if provider == "google" and os.environ.get("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = os.environ.get("GOOGLE_CHAT_MODEL", "gemini-2.0-flash")
        return ChatGoogleGenerativeAI(model=model, temperature=temperature)

    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        return ChatOpenAI(model=model, temperature=temperature)

    if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic

        model = os.environ.get("ANTHROPIC_CHAT_MODEL", "claude-sonnet-5")
        return ChatAnthropic(model=model, temperature=temperature)

    return None  # caller must fall back to mock/rule-based logic


def get_embeddings():
    """Returns a LangChain embeddings instance, or None if only mock mode is available."""
    provider = _provider()

    if provider == "google" and os.environ.get("GOOGLE_API_KEY"):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        model = os.environ.get("GOOGLE_EMBEDDING_MODEL", "models/text-embedding-004")
        return GoogleGenerativeAIEmbeddings(model=model)

    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import OpenAIEmbeddings

        model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return OpenAIEmbeddings(model=model)

    # Anthropic has no first-party embeddings API -- fall back to a local
    # deterministic hashing embedding so "anthropic" is still fully swappable
    # for generation while retrieval keeps working without an extra key.
    return None


def llm_available() -> bool:
    return get_chat_model() is not None


def embeddings_available() -> bool:
    return get_embeddings() is not None


try:
    from langchain_core.embeddings import Embeddings as _LCEmbeddingsBase
except ImportError:  # langchain_core not installed in this service (e.g. traceability-agent)
    _LCEmbeddingsBase = object


class MockEmbeddings(_LCEmbeddingsBase):
    """
    Deterministic hashing-based bag-of-words embedding, used only when no
    embeddings API key is configured, or the configured provider call fails
    (e.g. invalid key). Keeps the RAG pipeline fully functional offline;
    retrieval quality is naturally weaker than a real embedding model since
    it relies on lexical overlap.

    Subclasses LangChain's Embeddings base (when available) so vectorstores
    like FAISS treat it as a real embeddings object rather than a bare
    callable.
    """

    DIM = 384
    _STOPWORDS = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "for", "to", "in", "on", "at", "by", "with", "and", "or", "but",
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "it", "its", "as", "from", "into", "about", "does", "do", "did",
        "has", "have", "had", "can", "could", "should", "would", "will",
        "recommended", "please", "you", "your",
    }

    def _embed(self, text: str) -> list[float]:
        import hashlib
        import math
        import re

        vec = [0.0] * self.DIM
        tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in self._STOPWORDS]
        for tok in tokens:
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings_with_fallback():
    """get_embeddings(), or MockEmbeddings() if no provider key is configured."""
    emb = get_embeddings()
    if emb is not None:
        return emb
    return MockEmbeddings()
