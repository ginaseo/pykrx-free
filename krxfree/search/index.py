#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""knowledge/company/*/merged.json 에서 검색 가능한 Chunk 를 만든다.

Raw JSON 전체를 인덱싱하지 않는다 — 검색 가치가 있는 텍스트(Timeline Digest, Investment
Case)만 Chunk 로 뽑는다. Chunk 는 기업 단위가 아니라 의미 단위(기간별 Digest 한 줄,
Investment Case 한 건)로 쪼갠다.
"""
import os
import json

from ..paths import KNOWLEDGE_DIR


def _load_merged(code):
    p = os.path.join(KNOWLEDGE_DIR, code, "merged.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _period_to_date(period):
    """"YYYY"/"YYYY-QN"/"YYYY-MM" -> 정렬·날짜필터 비교용 YYYYMMDD 근사(그 기간의 첫날)."""
    if not period:
        return None
    if len(period) == 4:
        return f"{period}0101"
    if "Q" in period:
        y, q = period.split("-Q")
        month = (int(q) - 1) * 3 + 1
        return f"{y}{month:02d}01"
    if "-" in period:
        y, m = period.split("-")
        return f"{y}{m}01"
    return None


def build_index():
    """knowledge/company/*/merged.json 전체를 스캔해 Chunk 리스트 생성.

    지금 코퍼스 규모(종목 수·Chunk 수)에서는 검색할 때마다 다시 만들어도 비용이 무시할
    수준이라 별도 캐싱/영속 인덱스는 없음 — 코퍼스가 커지면(docs/DESIGN.md 채택 조건)
    이 함수 내부만 캐싱하도록 바꾸면 됨(외부 시그니처는 그대로)."""
    chunks = []
    if not os.path.isdir(KNOWLEDGE_DIR):
        return chunks
    for code in sorted(os.listdir(KNOWLEDGE_DIR)):
        merged = _load_merged(code)
        if not merged:
            continue
        tags = merged.get("tags", [])
        version = merged.get("version")

        for d in merged.get("digest", []):
            events = d.get("events") or []
            chunks.append({
                "text": f"{d.get('period')}: " + ", ".join(events),
                "chunk_type": "digest", "company_code": code, "tags": tags,
                "importance": None, "thesis_state": None,
                "date": _period_to_date(d.get("period")),
                "source": "knowledge", "schema_version": version,
            })

        for ic in merged.get("investment_cases", []):
            text = f"{ic.get('name')}: {ic.get('status')} ({ic.get('reason') or ''})"
            chunks.append({
                "text": text, "chunk_type": "investment_case", "company_code": code,
                "tags": ic.get("tags", []), "importance": ic.get("importance"),
                "thesis_state": ic.get("status"),
                "date": (ic.get("last_updated") or "").replace("-", "") or None,
                "source": "knowledge", "schema_version": version,
            })
    return chunks
