#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenDART 클라이언트 — 성장성/안정성/수익성 팩터용 (KRX 엔 없는 데이터)

- 인증키: .env 의 DART_API
- corp_code 매핑(종목코드->DART corp_code) 1회 다운로드 후 캐시(corp_map.json)
- fnlttSinglAcntAll(단일회사 전체 재무제표)에서 매출/영업이익/순이익/자본/부채 추출
  -> 매출성장률, 영업이익성장률, ROE, 부채비율 계산

[주의] 연결(CFS) 우선, 없으면 별도(OFS). 회계 구조상 근사치. 투자자문 아님.
"""

import os
import io
import json
import zipfile
import xml.etree.ElementTree as ET

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
_CORP_MAP = os.path.join(_HERE, "corp_map.json")
_SECTOR_MAP = os.path.join(_HERE, "sector_map.json")   # {종목코드: induty_code} 캐시
BASE = "https://opendart.fss.or.kr/api"


def _key():
    k = os.getenv("DART_API")
    if k:
        return k
    try:
        from dotenv import dotenv_values
        for c in (os.path.join(_HERE, ".env"), os.path.join(_HERE, "pykrx-master", ".env")):
            if os.path.exists(c):
                v = dotenv_values(c)
                if v.get("DART_API"):
                    return v["DART_API"]
    except Exception:
        pass
    return None


class DartError(RuntimeError):
    pass


def load_corp_map(force=False) -> dict:
    """{종목코드(6자리): corp_code(8자리)} 반환. 캐시 우선."""
    if not force and os.path.exists(_CORP_MAP):
        with open(_CORP_MAP, encoding="utf-8") as f:
            return json.load(f)
    key = _key()
    if not key:
        raise DartError(".env 에 DART_API 없음")
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    if r.status_code != 200 or r.content[:2] != b"PK":
        # JSON 에러 메시지일 수 있음
        raise DartError(f"corpCode 다운로드 실패: {r.text[:200]}")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    xml = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml)
    mp = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        if sc and cc:
            mp[sc] = cc
    with open(_CORP_MAP, "w", encoding="utf-8") as f:
        json.dump(mp, f, ensure_ascii=False)
    return mp


# 재무 항목 매핑 (account_id 우선, 이름 fallback)
_ACC = {
    # 금융/보험은 '매출액' 계정이 없음 -> 이자수익/보험료수익/영업수익 등으로 대체
    "revenue":  ({"ifrs-full_Revenue", "ifrs_Revenue"},
                 ("매출액", "영업수익", "수익(매출액)",
                  "이자수익", "보험료수익", "수수료수익", "영업수익(매출액)")),
    "op":       ({"dart_OperatingIncomeLoss", "ifrs-full_OperatingIncomeLoss"}, ("영업이익", "영업이익(손실)")),
    "ni":       ({"ifrs-full_ProfitLoss"}, ("당기순이익", "당기순이익(손실)", "분기순이익")),
    "equity":   ({"ifrs-full_Equity"}, ("자본총계",)),
    "liab":     ({"ifrs-full_Liabilities"}, ("부채총계",)),
    # 지배주주 기준 (PER/PBR 을 KRX 공식값에 맞추기 위함)
    "ni_owner": ({"ifrs-full_ProfitLossAttributableToOwnersOfParent"},
                 ("지배기업의 소유주에게 귀속되는 당기순이익",
                  "지배기업 소유주에게 귀속되는 당기순이익(손실)",
                  "지배기업 소유주지분 순이익", "지배주주순이익")),
    "eq_owner": ({"ifrs-full_EquityAttributableToOwnersOfParent"},
                 ("지배기업의 소유주에게 귀속되는 자본", "지배기업 소유주지분",
                  "지배기업소유주지분", "지배주주지분")),
}


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return None


def _pick(rows, ids, names):
    """매칭 항목의 (당기, 전기) 금액. account_id 우선(전체 1차 스캔) 후 이름 fallback."""
    # 1차: account_id 정확 매칭 (이름 충돌 방지)
    for r in rows:
        if (r.get("account_id") or "").strip() in ids:
            return _num(r.get("thstrm_amount")), _num(r.get("frmtrm_amount"))
    # 2차: account_nm 매칭
    for r in rows:
        if (r.get("account_nm") or "").strip() in names:
            return _num(r.get("thstrm_amount")), _num(r.get("frmtrm_amount"))
    return None, None


def financials(corp_code: str, year: int, reprt="11011"):
    """단일회사 재무지표 dict 반환. 실패 시 None.
    fs_div: 연결(CFS) 우선, 비면 별도(OFS).
    """
    key = _key()
    for fs in ("CFS", "OFS"):
        try:
            r = requests.get(
                f"{BASE}/fnlttSinglAcntAll.json",
                params={"crtfc_key": key, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": reprt, "fs_div": fs},
                timeout=30,
            )
            d = r.json()
        except Exception:
            continue
        if d.get("status") != "000":
            continue
        rows = d.get("list", [])
        rev_t, rev_p = _pick(rows, *(_ACC["revenue"]))
        op_t, op_p = _pick(rows, *(_ACC["op"]))
        ni_t, _ = _pick(rows, *(_ACC["ni"]))
        eq_t, _ = _pick(rows, *(_ACC["equity"]))
        li_t, _ = _pick(rows, *(_ACC["liab"]))
        ni_o, _ = _pick(rows, *(_ACC["ni_owner"]))
        eq_o, _ = _pick(rows, *(_ACC["eq_owner"]))
        if not any([rev_t, op_t, ni_t, eq_t]):
            continue

        def growth(t, p):
            if t is None or p in (None, 0):
                return None
            return round((t / p - 1) * 100, 1)

        # PER/PBR 계산은 지배주주 기준 우선(없으면 전체) -> KRX 공식값과 정합
        ni_for_eps = ni_o if ni_o is not None else ni_t
        eq_for_bps = eq_o if eq_o is not None else eq_t

        return {
            "fs": fs, "year": year,
            "revenue": rev_t, "op_income": op_t,
            "net_income": ni_t, "equity": eq_t, "liabilities": li_t,
            "net_income_owner": ni_o, "equity_owner": eq_o,
            "ni_for_eps": ni_for_eps, "eq_for_bps": eq_for_bps,
            "rev_growth_pct": growth(rev_t, rev_p),
            "op_growth_pct": growth(op_t, op_p),
            # ROE 도 지배주주 기준
            "roe_pct": (round(ni_for_eps / eq_for_bps * 100, 1)
                        if ni_for_eps is not None and eq_for_bps not in (None, 0) else None),
            "debt_ratio_pct": (round(li_t / eq_t * 100, 1)
                               if li_t is not None and eq_t not in (None, 0) else None),
        }
    return None


# ---------- 업종 분류 (company.json 의 induty_code = KSIC) ----------
# KSIC 대분류(앞 2자리) -> 거친 업종 버킷. 부채 감점 면제 판정(금융/보험)이 주 목적.
_KSIC2 = {
    "01": "농림어업", "02": "농림어업", "03": "농림어업",
    "05": "광업", "06": "광업", "07": "광업", "08": "광업",
    **{f"{n:02d}": "제조" for n in range(10, 34)},
    "35": "전기가스", "36": "수도환경", "37": "수도환경", "38": "수도환경", "39": "수도환경",
    "41": "건설", "42": "건설",
    "45": "도소매", "46": "도소매", "47": "도소매",
    "49": "운수", "50": "운수", "51": "운수", "52": "운수",
    "55": "숙박음식", "56": "숙박음식",
    "58": "정보통신", "59": "정보통신", "60": "정보통신",
    "61": "정보통신", "62": "정보통신", "63": "정보통신",
    "64": "금융", "66": "금융", "65": "보험",
    "68": "부동산",
    "70": "전문서비스", "71": "전문서비스", "72": "전문서비스", "73": "전문서비스",
}
_FINANCIAL = {"금융", "보험"}   # 구조적 고부채 -> 부채비율 감점 무의미


def base_code(code: str) -> str:
    """우선주 코드 -> 본주 코드(끝자리 5/6/7 등 -> 0). DART/업종은 회사 단위라 본주로 조회.
    예: 005935(삼성전자우) -> 005930. 끝자리 0이면 그대로."""
    code = str(code).strip()
    if len(code) == 6 and code[-1] != "0":
        return code[:5] + "0"
    return code


def company_info(corp_code: str):
    """DART 기업개황. {induty_code, corp_name} 반환, 실패 시 None."""
    key = _key()
    if not key or not corp_code:
        return None
    try:
        r = requests.get(f"{BASE}/company.json",
                         params={"crtfc_key": key, "corp_code": corp_code}, timeout=30)
        d = r.json()
    except Exception:
        return None
    if d.get("status") != "000":
        return None
    return {"induty_code": (d.get("induty_code") or "").strip(),
            "corp_name": d.get("corp_name")}


def sector_bucket(induty_code: str):
    """KSIC induty_code -> 업종 버킷. 미상이면 '기타', 빈값이면 None."""
    if not induty_code:
        return None
    return _KSIC2.get(induty_code[:2], "기타")


def is_financial(sector: str) -> bool:
    return sector in _FINANCIAL


def sectors_for(stock_codes, corp_map: dict) -> dict:
    """{종목코드: 업종버킷} 반환. induty_code 는 sector_map.json 에 캐시(빈값도 저장해 재호출 방지)."""
    try:
        with open(_SECTOR_MAP, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    changed = False
    out = {}
    for sc in stock_codes:
        ind = cache.get(sc)
        if ind is None:                       # 미캐시 -> 조회 (우선주는 본주로 폴백)
            cc = corp_map.get(sc) or corp_map.get(base_code(sc))
            info = company_info(cc)
            ind = (info or {}).get("induty_code", "") or ""
            cache[sc] = ind
            changed = True
        out[sc] = sector_bucket(ind)
    if changed:
        try:
            with open(_SECTOR_MAP, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass
    return out


def per_pbr(fin: dict, close: float, shares: float):
    """지배주주 기준 PER/PBR 계산. (close=종가, shares=상장주식수)"""
    if not fin or not shares:
        return None, None
    ni = fin.get("ni_for_eps")
    eq = fin.get("eq_for_bps")
    per = round(close / (ni / shares), 1) if ni and ni != 0 else None
    pbr = round(close / (eq / shares), 2) if eq and eq != 0 else None
    return per, pbr


if __name__ == "__main__":
    mp = load_corp_map()
    print("corp_map size:", len(mp))
    for code, nm in [("005930", "삼성전자"), ("000270", "기아"), ("035420", "NAVER")]:
        cc = mp.get(code)
        f = financials(cc, 2025) if cc else None
        print(f"{code} {nm} corp={cc} ->", f)
