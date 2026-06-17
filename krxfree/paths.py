# -*- coding: utf-8 -*-
"""프로젝트 경로 한 곳에서 관리. 데이터/캐시/산출물은 모두 저장소 루트 기준."""
import os

# krxfree/paths.py -> krxfree -> 저장소 루트
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "results")


def env_candidates():
    """`.env` 후보 경로. 클라이언트들이 인증키/자격증명 로드에 사용."""
    return (os.path.join(ROOT, ".env"),)


def data_path(name):
    """루트 기준 데이터/캐시 파일 경로(corp_map.json, portfolio.json 등)."""
    return os.path.join(ROOT, name)
