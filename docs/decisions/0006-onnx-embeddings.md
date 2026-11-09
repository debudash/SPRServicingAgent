# 0006. Embeddings through Chroma's bundled ONNX model, not sentence-transformers

Date: 2026-11-09 · Status: accepted · Decided by: integrator · Issue: #26

## Context
The default demo stack embeds locally with sentence-transformers, as v1 did. That library pulls in PyTorch:
about 2 GB with GPU wheels on Linux, a few hundred MB with CPU-only wheels from a separate index. Every
night-shift agent run and every CI job installs the full requirements, and the Docker image ships them.

## Decision
Embed with Chroma's built-in `DefaultEmbeddingFunction`: the same `all-MiniLM-L6-v2` model v1 used, run
through ONNX Runtime, local and offline once the model file is cached. No PyTorch.

- **Tests never download the model.** Unit tests pass a deterministic fake embedding function; the real
  model is used only by `make ingest` and the running desk.
- **The model is fetched once** (about 80 MB) on first ingest and cached in Chroma's cache folder, which
  `compose.yaml` mounts from `var/cache`, so it survives container rebuilds.

## Consequences
- Agent runners and CI install in seconds, not minutes, and the image stays small.
- Embeddings match v1's model, so retrieval quality is comparable with the baseline.
- One stack deviation from the default (sentence-transformers), recorded here.

## Alternatives rejected
- **sentence-transformers with CPU-only PyTorch.** Works, but needs a second package index pinned in every
  install path, and is still far heavier than ONNX Runtime.
- **A hosted embedding API.** Adds a network dependency and a key at demo time; the stack is local-first.
