#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Processor 등록소. 새 Processor 추가 시 @register("이름") 만 붙이면 pipeline.py 는
그 이름을 리스트에 넣기만 하면 된다(개별 모듈을 다시 import/배선할 필요 없음)."""

_REGISTRY = {}


def register(name):
    def deco(fn):
        _REGISTRY[name] = fn
        return fn
    return deco


def get(name):
    return _REGISTRY[name]


def names():
    return list(_REGISTRY.keys())
