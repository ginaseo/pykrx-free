# -*- coding: utf-8 -*-
"""Search Layer — Knowledge(knowledge/company/*/merged.json)를 검색하는 공통 API.

지금은 KeywordSearchBackend 만 있다. 임베딩/벡터DB 는 지금 규모(종목 수·Chunk 수)에서
과설계(YAGNI)라 도입하지 않았다 — 채택 조건은 docs/DESIGN.md 참조. SearchEngine 인터페이스만
먼저 고정해 두고, 조건이 차면 backend 만 교체한다(호출부 변경 없음).
"""
