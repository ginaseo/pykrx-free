#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SearchBackend 추상 인터페이스. 구현체를 교체(Keyword -> Embedding/Hybrid)해도
SearchEngine 이하 호출부는 바뀌지 않는다."""

from abc import ABC, abstractmethod


class SearchBackend(ABC):
    @abstractmethod
    def search(self, query, filters, top_k):
        """chunk dict 리스트(관련도 내림차순) 반환. filters=None 이면 전체 대상."""
