#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""산업 테마 태그 — 향후 뉴스·매크로와 결합할 Context Builder(보류) 의 입력값 준비 단계.
규칙 기반 키워드 매칭만 한다(LLM 추론 없음). 매칭 없으면 빈 리스트(억지로 태그 안 붙임)."""

TAG_KEYWORDS = {
    "AI": ("AI", "인공지능"),
    "HBM": ("HBM", "고대역폭메모리"),
    "Memory": ("메모리", "D램", "낸드"),
    "Cloud": ("클라우드",),
    "EV": ("전기차", "EV"),
    "Battery": ("배터리", "이차전지"),
    "Renewable": ("태양광", "재생에너지", "친환경"),
    "Semiconductor": ("반도체", "파운드리"),
}


def match_tags(text: str):
    """text 안에 TAG_KEYWORDS 매칭되는 태그 리스트(중복 없음, 정의 순서 유지)."""
    text = text or ""
    return [tag for tag, kws in TAG_KEYWORDS.items() if any(kw in text for kw in kws)]
