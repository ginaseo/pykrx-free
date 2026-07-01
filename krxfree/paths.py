# -*- coding: utf-8 -*-
"""프로젝트 경로 한 곳에서 관리. 데이터/캐시/산출물은 모두 저장소 루트 기준."""
import os

# krxfree/paths.py -> krxfree -> 저장소 루트
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "results")
KNOWLEDGE_DIR = os.path.join(ROOT, "knowledge", "company")   # 브리핑(results/)과 분리된 장기 누적 데이터


def env_candidates():
    """`.env` 후보 경로. 클라이언트들이 인증키/자격증명 로드에 사용."""
    return (os.path.join(ROOT, ".env"),)


def data_path(name):
    """루트 기준 데이터/캐시 파일 경로(corp_map.json, portfolio.json 등)."""
    return os.path.join(ROOT, name)


def company_knowledge_path(code: str, filename: str) -> str:
    """knowledge/company/{code}/{filename} 경로(manual.json/dart.json/generated.json/merged.json).
    디렉터리 없으면 생성(파일 자체는 만들지 않음 — 없으면 각 Processor 가 빈 값으로 처리)."""
    d = os.path.join(KNOWLEDGE_DIR, code)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, filename)
