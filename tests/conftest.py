import pytest


class FakeEmbeddings:
    """Deterministic fake embeddings: avoids downloading the real model in CI/tests."""

    def embed_documents(self, texts):
        return [self._fake_vector(t) for t in texts]

    def embed_query(self, text):
        return self._fake_vector(text)

    @staticmethod
    def _fake_vector(text):
        # Components vary by index on purpose: constant vectors have cosine
        # distance 0 to each other and make retrieval tests meaningless.
        seed = sum(ord(c) for c in text) % 1000
        return [((seed + i) % 100) / 100.0 for i in range(384)]


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    """Applied to every test: replaces the real embedding model with the fake."""
    from src import embeddings

    fake = FakeEmbeddings()
    monkeypatch.setattr(embeddings, "_embeddings", fake)
    monkeypatch.setattr(embeddings, "get_embeddings", lambda: fake)
    yield fake
