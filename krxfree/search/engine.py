#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공통 Search API. 지금은 KeywordSearchBackend 뿐이지만, 코퍼스가 커지면(docs/DESIGN.md
채택 조건) EmbeddingSearchBackend/HybridSearchBackend 로 교체해도 이 파일 밖 호출부(SearchEngine
사용처)는 바뀌지 않는다.

독립 실행: python -m krxfree.search.engine <검색어>
"""
import sys
import json

from .index import build_index
from .backends.keyword_backend import KeywordSearchBackend


class SearchEngine:
    def __init__(self, backend):
        self._backend = backend

    def search(self, query, filters=None, top_k=10):
        """filters: company_code/chunk_type/thesis_state/tag/date_from/date_to."""
        return self._backend.search(query, filters, top_k)


def default_engine():
    """현재 기본 구현(KeywordSearchBackend). 백엔드 교체 시 이 함수만 바꾸면 됨."""
    return SearchEngine(KeywordSearchBackend(build_index()))


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(default_engine().search(q), ensure_ascii=False, indent=2))
