#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Knowledge 계층 파일(manual/dart/generated/merged.json) 공통 로드/저장.

파일이 없으면 기본값(정상 — 첫 실행 등). **파일이 있는데 파싱 실패하면 예외를 그대로
던진다** — 조용히 빈 값으로 대체하면 이후 저장 단계에서 기존에 누적된 timeline/digest/
investment_cases 가 통째로 덮어써질 위험이 있음(point14 "삭제 없음, 증분만" 원칙 위반).
호출부(screener.py 의 `knowledge_pipeline.run`)가 이미 try/except 로 감싸므로 여기서
예외가 나도 브리핑 생성 자체는 막히지 않는다 — 이번 실행의 Knowledge 갱신만 건너뛴다.
"""
import os
import json
import datetime

from ..paths import company_knowledge_path


def load(code, filename, default=None):
    p = company_knowledge_path(code, filename)
    if not os.path.exists(p):
        return dict(default) if default is not None else {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(code, filename, data):
    data["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    p = company_knowledge_path(code, filename)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
