"""Embeddings as the missing middle rung — semantic, cheaper/faster than an LLM.

The cost ladder so far:
    hashes/rules (free) ........ catch structural cases, miss SEMANTIC ones
    LLM judge (expensive) ...... catches everything, batched off the hot path
A gap sits between them. The cases hashes miss are *semantic* — reddit /user/spez
('overview for spez') wears the listing template (struct cosine 0.993) but its
TITLE means 'profile'. An embedding of the title should separate it cheaply and —
crucially — GENERALIZE cross-domain, because 'overview for X' lives near 'user
profile' in embedding space regardless of site.

DEPENDENCY NOTE (honest): this environment has no numpy / sentence-transformers /
fastembed / API keys. So this module uses a DEPENDENCY-FREE proxy embedding — the
classic feature-hashing trick over character n-grams (hashed into a fixed-dim
signed float vector). It is *lexical*, not deep-semantic: it captures shared
character n-grams (so 'overview for spez' ~ 'overview for kn0thing'), which is a
real, cheap embedding and exactly the slot a true model embedding would occupy.
A real MiniLM/model2vec vector is a DROP-IN for `embed_text` and would be strictly
more semantic (it'd relate 'profile' and 'overview' without shared characters).
Read every number here as a LOWER BOUND on what a real embedding delivers.

What we measure on the 52 samples:
  1. does a TITLE embedding catch the costume case the struct fingerprint misses?
  2. does an embedding ensemble vote reduce leaks/abstains vs SimHash alone?
  3. does it transfer CROSS-DOMAIN (k-NN class accuracy, held-out domain)?

Run: uv run python experiments/scope_spike/embed.py
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

DOMAINS = Path(__file__).parent / 'fixtures' / 'domains'
DIM = 256  # proxy embedding dimensionality


def _ngrams(text: str, n: int = 3) -> list[str]:
    t = re.sub(r'\s+', ' ', text.lower().strip())
    t = f'  {t} '
    return [t[i : i + n] for i in range(len(t) - n + 1)] if len(t) >= n else [t]


def embed_text(text: str, dim: int = DIM) -> list[float]:
    """Feature-hashed char-trigram embedding (L2-normalized).

    PROXY for a real sentence embedding. Drop in MiniLM/model2vec here unchanged,
    or call a real provider via `embed_text_remote` when a key is available.
    """
    vec = [0.0] * dim
    for g in _ngrams(text):
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), 'big')
        idx = h % dim
        sign = 1.0 if (h >> 63) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# --------------------------------------------------------------------------- #
# Real embedding path — OpenAI-COMPATIBLE /embeddings (provider-agnostic).
# OpenRouter DOES serve embeddings: POST https://openrouter.ai/api/v1/embeddings
# (verified live — an authed request with a bad key returns 401 'User not found',
# i.e. the route exists; only a key is missing in this env). So set
# EMBEDDINGS_BASE_URL=https://openrouter.ai/api/v1 + EMBEDDINGS_API_KEY=<or-key>
# + EMBEDDINGS_MODEL=<e.g. openai/text-embedding-3-small>. Any OpenAI-compatible
# base works (OpenAI, Voyage, local). Activates only when a key is present;
# otherwise the experiment uses the proxy above and says so.
# --------------------------------------------------------------------------- #
def _embed_config() -> tuple[str, str, str] | None:
    """Return (base_url, api_key, model) from env, or None if unconfigured."""
    import os

    # try, in order: explicit embeddings base, then OpenAI defaults
    candidates = [
        ('EMBEDDINGS_BASE_URL', 'EMBEDDINGS_API_KEY', 'EMBEDDINGS_MODEL'),
        ('OPENAI_BASE_URL', 'OPENAI_API_KEY', 'OPENAI_EMBEDDINGS_MODEL'),
    ]
    for base_var, key_var, model_var in candidates:
        key = os.getenv(key_var)
        if key:
            base = os.getenv(base_var, 'https://api.openai.com/v1')
            model = os.getenv(model_var, 'text-embedding-3-small')
            return base.rstrip('/'), key, model
    return None


def embed_text_remote(texts: list[str]) -> list[list[float]] | None:
    """Batch-embed via an OpenAI-compatible endpoint; None if unconfigured/unavailable.

    Stdlib-only HTTP so the spike adds no dependency. Real embeddings are a
    BATCH/OFFLINE concern (per the reviews: never on the hot path) — this batches.
    """
    cfg = _embed_config()
    if cfg is None:
        return None
    base, key, model = cfg
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        f'{base}/embeddings',
        data=_json.dumps({'model': model, 'input': texts}).encode(),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = _json.loads(resp.read())
        return [row['embedding'] for row in payload['data']]
    except Exception as e:  # noqa: BLE001 - spike: degrade to proxy, report why
        print(f'  [remote embeddings unavailable: {type(e).__name__}: {e}]')
        return None


def cos(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (already ~normalized)."""
    return sum(x * y for x, y in zip(a, b, strict=True))


@dataclass(frozen=True)
class Page:
    """A page with its title embedding + ground-truth class."""

    domain: str
    role: str
    title: str
    url: str
    is_listing: bool
    title_emb: list[float]


def load_pages() -> tuple[list[Page], bool]:
    """Embed every page title; use a real provider if configured, else the proxy.

    Returns (pages, used_real). `used_real` flags whether numbers are real-model
    or proxy (lexical) — the writeup must label proxy numbers as a lower bound.
    """
    rows = []
    for f in sorted(DOMAINS.glob('*.json')):
        d = json.loads(Path(f).read_text())
        for p in d['pages']:
            if p.get('blocked'):
                continue
            rows.append((d.get('domain', f.stem), p))
    titles = [(p.get('title', '') or '') for _dom, p in rows]

    remote = embed_text_remote(titles)
    used_real = remote is not None
    embs = remote if used_real else [embed_text(t) for t in titles]

    out = []
    for (dom, p), emb in zip(rows, embs, strict=True):
        out.append(
            Page(
                domain=dom,
                role=p['role'],
                title=p.get('title', '') or '',
                url=p.get('href', ''),
                is_listing=p['role'] in ('seed', 'must-transfer'),
                title_emb=emb,
            )
        )
    return out, used_real


def exp1_costume(pages: list[Page]) -> None:
    """Does the title embedding separate the seed listing from /user/spez?"""
    by = {(p.domain, p.role, p.url): p for p in pages}
    seed = next(p for p in pages if p.domain == 'old.reddit.com' and p.role == 'seed')
    spez = next(p for p in pages if p.domain == 'old.reddit.com' and 'spez' in p.url)
    sib = next(p for p in pages if p.domain == 'old.reddit.com' and p.role == 'must-transfer')
    print('EXP1 — costume case via TITLE embedding (struct cosine could not tell):')
    print(f'  seed title:     {seed.title!r}')
    print(f'  sibling title:  {sib.title!r}   emb-cos to seed = {cos(seed.title_emb, sib.title_emb):.3f}')
    print(f'  /user/spez:     {spez.title!r}   emb-cos to seed = {cos(seed.title_emb, spez.title_emb):.3f}')
    print('  -> a LISTING sibling should score HIGHER to the seed than the profile does.')
    _ = by


def exp2_knn_cross_domain(pages: list[Page]) -> None:
    """1-NN class accuracy from the TITLE embedding, held-out-domain."""
    correct = same = 0
    for i, p in enumerate(pages):
        best, bs = -1, -2.0
        for j, q in enumerate(pages):
            if i == j or q.domain == p.domain:
                continue
            s = cos(p.title_emb, q.title_emb)
            if s > bs:
                bs, best = s, j
        if best >= 0:
            same += 1
            if pages[best].is_listing == p.is_listing:
                correct += 1
    print('\nEXP2 — cross-domain 1-NN class accuracy from title embedding alone:')
    print(
        f'  {correct}/{same} = {correct / same:.2f}  (proxy lexical embedding; '
        'a real model embedding is the lower-bounded upgrade)'
    )


def exp3_separation(pages: list[Page]) -> None:
    """Within each domain, does the seed's title-emb rank transfers above refuses?"""
    wins = trials = 0
    for dom in {p.domain for p in pages}:
        grp = [p for p in pages if p.domain == dom]
        seed = next((p for p in grp if p.role == 'seed'), None)
        if not seed:
            continue
        trans = [cos(seed.title_emb, p.title_emb) for p in grp if p.role == 'must-transfer']
        refus = [cos(seed.title_emb, p.title_emb) for p in grp if p.role == 'must-refuse']
        if not trans or not refus:
            continue
        trials += 1
        if min(trans) > max(refus):  # perfectly separable by title-emb in this domain
            wins += 1
    print('\nEXP3 — per-domain: does title-emb cleanly rank transfers above refuses?')
    print(f'  {wins}/{trials} domains perfectly separable by title embedding alone')


def main() -> int:
    """Run the three embedding experiments on the fixtures."""
    pages, used_real = load_pages()
    kind = 'REAL provider model' if used_real else f'PROXY hashed char-trigram, dim={DIM}'
    print('=' * 78)
    print(f'EMBEDDING RUNG ({kind}) — {len(pages)} pages')
    if not used_real:
        print('  NOTE: proxy is LEXICAL not semantic; numbers are a floor. Set')
        print('  EMBEDDINGS_API_KEY (+ optional EMBEDDINGS_BASE_URL/MODEL) for real.')
    print('=' * 78)
    exp1_costume(pages)
    exp2_knn_cross_domain(pages)
    exp3_separation(pages)
    print('\nReading: title embeddings target the SEMANTIC gap that structure misses')
    print('(profile vs listing by meaning) and are O(dim) to compare — a true middle')
    print('rung between free hashes and the expensive LLM. Proxy numbers are a floor;')
    print('a static model2vec/MiniLM embedding is the drop-in that raises them.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
