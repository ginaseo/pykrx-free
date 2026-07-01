#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""키워드(부분일치) 검색. 임베딩·벡터DB 의존성 없음 — 현재 코퍼스 규모(종목 수십·Chunk 수백
이내)에 맞춘 최소 구현. 코퍼스가 커지면(docs/DESIGN.md 채택 조건 참조) 이 파일만 교체."""

from .base import SearchBackend


def _score(terms, text):
    text = (text or "").lower()
    return sum(text.count(t) for t in terms)


def _match_filters(chunk, filters):
    for key in ("company_code", "chunk_type", "thesis_state"):
        want = filters.get(key)
        if want is not None and chunk.get(key) != want:
            return False
    tag = filters.get("tag")
    if tag is not None and tag not in (chunk.get("tags") or []):
        return False
    date_from = filters.get("date_from")
    if date_from and (chunk.get("date") or "") < date_from:
        return False
    date_to = filters.get("date_to")
    if date_to and (chunk.get("date") or "99999999") > date_to:
        return False
    return True


class KeywordSearchBackend(SearchBackend):
    def __init__(self, chunks):
        self._chunks = chunks

    def search(self, query, filters=None, top_k=10):
        terms = [t for t in (query or "").lower().split() if t]
        filters = filters or {}
        scored = []
        for c in self._chunks:
            if not _match_filters(c, filters):
                continue
            score = _score(terms, c.get("text", "")) if terms else 1
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda sc: sc[0], reverse=True)
        return [c for _, c in scored[:top_k]]
