import os

from fastembed import TextEmbedding

# fastembed's TextEmbedding.embed() defaults to batch_size=256, i.e. every
# chunk is padded to the longest sequence and run through the ONNX model in a
# single forward pass. Memory scales with batch_size * seq_len^2 (attention);
# on the old project this OOM'd a 512MB host (measured RSS ~669MB at 256 vs
# ~283MB at 8). Always pass an explicit batch_size.
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "8"))
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


class _FastEmbedWrapper:
    def __init__(self):
        self._model = TextEmbedding(model_name=MODEL_NAME, cache_dir=os.environ.get("FASTEMBED_CACHE_DIR") or None)

    def embed_documents(self, texts):
        return [vec.tolist() for vec in self._model.embed(texts, batch_size=EMBED_BATCH_SIZE)]

    def embed_query(self, text):
        return next(iter(self._model.embed([text], batch_size=1))).tolist()


_embeddings = None


def get_embeddings():
    """Lazy singleton: loading the model is expensive, don't reload per call."""
    global _embeddings
    if _embeddings is None:
        _embeddings = _FastEmbedWrapper()
    return _embeddings
