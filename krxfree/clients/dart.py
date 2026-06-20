#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenDART 클라이언트 — 성장성/안정성/업종 팩터용 (KRX 엔 없는 데이터)

- 인증키: .env 의 DART_API
- corp_code 매핑(종목코드->DART corp_code) 1회 다운로드 후 캐시(corp_map.json)
- fnlttSinglAcntAll(단일회사 전체 재무제표)에서 매출/영업이익/순이익/자본/부채 추출
  -> 매출성장률, 영업이익성장률, ROE, 부채비율 계산
- company.json(기업개황) induty_code(KSIC) -> 업종 버킷 (sector_map.json 캐시)

[주의] 연결(CFS) 우선, 없으면 별도(OFS). 회계 구조상 근사치. 투자자문 아님.
"""

import os
import io
import json
import zipfile
import xml.etree.ElementTree as ET

import requests

from ..paths import env_candidates, data_path

_CORP_MAP = data_path("corp_map.json")
_SECTOR_MAP = data_path("sector_map.json")   # {종목코드: induty_code} 캐시
BASE = "https://opendart.fss.or.kr/api"


def _key():
    k = os.getenv("DART_API")
    if k:
        return k
    try:
        from dotenv import dotenv_values
        for c in env_candidates():
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
    for r in rows:
        if (r.get("account_id") or "").strip() in ids:
            return _num(r.get("thstrm_amount")), _num(r.get("frmtrm_amount"))
    for r in rows:
        if (r.get("account_nm") or "").strip() in names:
            return _num(r.get("thstrm_amount")), _num(r.get("frmtrm_amount"))
    return None, None


def financials(corp_code: str, year: int, reprt="11011"):
    """단일회사 재무지표 dict 반환. 실패 시 None. fs_div: 연결(CFS) 우선, 비면 별도(OFS)."""
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
    """지배주주 기준 PER/PBR 계산. (close=종가, shares=상장주식수)

    [주의] 근사값(KRX 공식값과 ±0~22% 차이). 출력엔 사용하지 않음 — DESIGN.md 데이터 원칙 참조.
    """
    if not fin or not shares:
        return None, None
    ni = fin.get("ni_for_eps")
    eq = fin.get("eq_for_bps")
    per = round(close / (ni / shares), 1) if ni and ni != 0 else None
    pbr = round(close / (eq / shares), 2) if eq and eq != 0 else None
    return per, pbr


# ---------- 공시 필터 (Phase1: 호재/악재 키워드 분류) ----------
# report_nm 부분일치. 강한 악재는 후보 제외급, 중간 악재는 감점, 호재는 소폭 가점.
HARD_NEGATIVE_KW = ("감자결정", "관리종목지정", "상장폐지", "횡령", "배임", "회생절차")
SOFT_NEGATIVE_KW = ("유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정", "교환사채권발행결정")
POSITIVE_KW = ("자기주식취득결정", "자기주식취득신탁계약체결결정", "단일판매공급계약체결")


def classify_disclosure(report_nm: str):
    """공시 제목 -> 'hard_negative'/'soft_negative'/'positive'/None."""
    nm = report_nm or ""
    for kw in HARD_NEGATIVE_KW:
        if kw in nm:
            return "hard_negative"
    for kw in SOFT_NEGATIVE_KW:
        if kw in nm:
            return "soft_negative"
    for kw in POSITIVE_KW:
        if kw in nm:
            return "positive"
    return None


def disclosures(corp_code: str, bgn_de: str, end_de: str):
    """기간 내 공시 목록(list.json) 원본 리스트.

    키 없으면 기능 OFF로 보고 []. 네트워크/파싱/예상밖 상태코드는 **None**(조회 실패 = 모름)
    — "공시 없음"(013, 정상 응답)과 절대 같은 값으로 섞지 않는다. 호출부가 None 을
    "위험 없음"으로 오인하면 안 되기 때문(예: API 장애 시 보유종목을 '양호'로 오판).
    """
    key = _key()
    if not key or not corp_code:
        return []
    try:
        r = requests.get(f"{BASE}/list.json", params={
            "crtfc_key": key, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de, "page_count": 100,
        }, timeout=30)
        d = r.json()
    except Exception:
        return None
    if d.get("status") == "013":   # 013 = 조회된 데이터 없음(정상, 진짜 빈 결과)
        return []
    if d.get("status") != "000":
        return None
    return d.get("list") or []


def disclosure_flags(corp_code: str, bgn_de: str, end_de: str):
    """기간 내 공시를 분류해 {"hard_negative": [...], "soft_negative": [...], "positive": [...]} 반환.
    각 항목은 {"report_nm", "rcept_dt"}. 조회 자체가 실패하면 **None**(disclosures 참조)."""
    items = disclosures(corp_code, bgn_de, end_de)
    if items is None:
        return None
    out = {"hard_negative": [], "soft_negative": [], "positive": []}
    for it in items:
        cat = classify_disclosure(it.get("report_nm") or "")
        if cat:
            out[cat].append({"report_nm": it.get("report_nm"), "rcept_dt": it.get("rcept_dt")})
    return out


# ---------- 유상증자/CB 상세 (Phase2: 배정방식 + 희석규모로 감점폭 세분화) ----------
def capital_increase_items(corp_code: str, bgn_de: str, end_de: str):
    """유상증자결정(piicDecsn) 상세 목록. 키 없으면 []. 조회 실패는 None(disclosures 참조)."""
    key = _key()
    if not key or not corp_code:
        return []
    try:
        r = requests.get(f"{BASE}/piicDecsn.json", params={
            "crtfc_key": key, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de,
        }, timeout=30)
        d = r.json()
    except Exception:
        return None
    if d.get("status") == "013":
        return []
    if d.get("status") != "000":
        return None
    return d.get("list") or []


def cb_issue_items(corp_code: str, bgn_de: str, end_de: str):
    """전환사채권발행결정(cvbdIsDecsn) 상세 목록. 키 없으면 []. 조회 실패는 None(disclosures 참조)."""
    key = _key()
    if not key or not corp_code:
        return []
    try:
        r = requests.get(f"{BASE}/cvbdIsDecsn.json", params={
            "crtfc_key": key, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de,
        }, timeout=30)
        d = r.json()
    except Exception:
        return None
    if d.get("status") == "013":
        return []
    if d.get("status") != "000":
        return None
    return d.get("list") or []


def _piic_detail(item: dict):
    """유상증자결정 한 건 -> {method(배정방식), raise_amount_won(조달금액), dilution_pct(희석률)}."""
    raise_amt = sum((_num(item.get(k)) or 0) for k in
                     ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"))
    new_shares = (_num(item.get("nstk_ostk_cnt")) or 0) + (_num(item.get("nstk_estk_cnt")) or 0)
    base_shares = (_num(item.get("bfic_tisstk_ostk")) or 0) + (_num(item.get("bfic_tisstk_estk")) or 0)
    return {
        "method": item.get("ic_mthn"),
        "raise_amount_won": raise_amt or None,
        "dilution_pct": round(new_shares / base_shares * 100, 1) if base_shares else None,
    }


def _cvbd_detail(item: dict):
    """전환사채권발행결정 한 건 -> {method(발행방법), amount_won(권면총액)}."""
    return {"method": item.get("bdis_mthn"), "amount_won": _num(item.get("bd_fta"))}


def dilution_flags(corp_code: str, bgn_de: str, end_de: str):
    """기간 내 유상증자/CB 상세. {"capital_increase": [...], "convertible_bond": [...]}.
    둘 중 하나라도 조회 실패면 None(disclosures 참조)."""
    ci = capital_increase_items(corp_code, bgn_de, end_de)
    cb = cb_issue_items(corp_code, bgn_de, end_de)
    if ci is None or cb is None:
        return None
    return {
        "capital_increase": [_piic_detail(it) for it in ci],
        "convertible_bond": [_cvbd_detail(it) for it in cb],
    }


def dilution_severity(flags: dict) -> float:
    """배정방식·희석률 기반 감점폭. 제3자배정/일반공모 + 희석 10%↑ 는 강한 감점."""
    penalty = 0.0
    for ci in flags.get("capital_increase", []):
        method = ci.get("method") or ""
        dp = ci.get("dilution_pct") or 0
        hard_method = ("제3자배정" in method) or ("일반공모" in method)
        if hard_method and dp >= 10:
            penalty -= 0.08
        elif dp >= 10:
            penalty -= 0.05
        else:
            penalty -= 0.02
    for _cb in flags.get("convertible_bond", []):
        penalty -= 0.05   # 시총 대비 비율 산출 어려움(권면총액만 제공) -> 기존 고정 감점 유지
    return penalty


if __name__ == "__main__":
    mp = load_corp_map()
    print("corp_map size:", len(mp))
    for code, nm in [("005930", "삼성전자"), ("000270", "기아"), ("035420", "NAVER")]:
        cc = mp.get(code)
        f = financials(cc, 2025) if cc else None
        print(f"{code} {nm} corp={cc} ->", f)
