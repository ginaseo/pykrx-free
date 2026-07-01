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
        ni_t, ni_t_p = _pick(rows, *(_ACC["ni"]))
        eq_t, eq_t_p = _pick(rows, *(_ACC["equity"]))
        li_t, li_t_p = _pick(rows, *(_ACC["liab"]))
        ni_o, ni_o_p = _pick(rows, *(_ACC["ni_owner"]))
        eq_o, eq_o_p = _pick(rows, *(_ACC["eq_owner"]))
        if not any([rev_t, op_t, ni_t, eq_t]):
            continue

        def growth(t, p):
            if t is None or p in (None, 0):
                return None
            return round((t / p - 1) * 100, 1)

        # PER/PBR 계산은 지배주주 기준 우선(없으면 전체) -> KRX 공식값과 정합
        ni_for_eps = ni_o if ni_o is not None else ni_t
        eq_for_bps = eq_o if eq_o is not None else eq_t
        # 전기(frmtrm) 지배주주 순이익/자본 -> ROE 전년 대비 개선 판정용(같은 API 응답에 이미 포함된 값, 추가 호출 없음)
        ni_for_eps_p = ni_o_p if ni_o_p is not None else ni_t_p
        eq_for_bps_p = eq_o_p if eq_o_p is not None else eq_t_p

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
            "roe_prev_pct": (round(ni_for_eps_p / eq_for_bps_p * 100, 1)
                             if ni_for_eps_p is not None and eq_for_bps_p not in (None, 0) else None),
            "debt_ratio_prev_pct": (round(li_t_p / eq_t_p * 100, 1)
                                    if li_t_p is not None and eq_t_p not in (None, 0) else None),
        }
    return None


def fin_events(fin: dict):
    """재무제표 기반 Thesis 이벤트(ROE 개선/부채 감소). 전기 대비 실측 비교만 사용(추정 없음).

    ponytail: 배당확대·실적서프라이즈·ROIC·FCF·현금흐름개선은 이번 버전 제외 —
    배당 방향(원문 파싱 필요)/컨센서스(데이터 없음)/ROIC·FCF(현금흐름표 계정 매핑 미비)라
    근사 없이는 계산 불가. 향후 계정 매핑·API 확장 시 추가.
    날짜는 rcept_dt 형식(YYYYMMDD)에 맞춰 사업연도 말일(YYYY1231)로 부여 —
    공시 이벤트와 동일한 decay/타임라인 로직을 그대로 태울 수 있게.
    """
    if not fin:
        return []
    out = []
    year = fin.get("year")
    fy_end = f"{year}1231" if year else None
    if not fy_end:
        return []
    roe_p, roe_c = fin.get("roe_prev_pct"), fin.get("roe_pct")
    if roe_p is not None and roe_c is not None and (roe_c - roe_p) >= 1:
        out.append({
            "report_nm": f"{year} 사업보고서(ROE {roe_p}%→{roe_c}%)", "rcept_dt": fy_end,
            "rcept_no": None, "dart_link": None, "event_type": "roe_improvement",
            "level": "A", "confidence": "HIGH", "classification": "DART",
            "severity": 2, "impact_score": 1, "reason": "ROE 개선",
        })
    dr_p, dr_c = fin.get("debt_ratio_prev_pct"), fin.get("debt_ratio_pct")
    if dr_p is not None and dr_c is not None and (dr_p - dr_c) >= 10:
        out.append({
            "report_nm": f"{year} 사업보고서(부채비율 {dr_p}%→{dr_c}%)", "rcept_dt": fy_end,
            "rcept_no": None, "dart_link": None, "event_type": "debt_reduction",
            "level": "A", "confidence": "HIGH", "classification": "DART",
            "severity": 2, "impact_score": 2, "reason": "부채 감소",
        })
    return out


def dilution_extra_penalty(pct):
    """유상증자 희석률 구간별 추가 감점(유상증자 자체 감점과 별개 -> Thesis contributors 에
    별도 항목으로 노출). 10~20%: -1, 20~30%: -2, 30%↑: -3. 10% 미만은 추가 감점 없음."""
    if pct is None:
        return 0
    if pct >= 30:
        return -3
    if pct >= 20:
        return -2
    if pct >= 10:
        return -1
    return 0


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


# ---------- Thesis Impact Engine: 공시 이벤트 taxonomy (제목 키워드 분류) ----------
# report_nm 부분일치, 순서대로 첫 매치 채택(구체적인 것 먼저).
# 각 규칙: (키워드들, event_type, category("dart"/"krx"), level("A"=구조화 신뢰,
#           "B"=키워드 참고, "C"=시장경보 보류), confidence, severity(1~5, 공시 자체 중요도),
#           impact_score(Thesis 영향도, None=방향 불명 -> 점수 미반영), reason)
# level A만 Thesis Impact Score 합산 대상(B/C는 참고 표시만, 향후 구조화 데이터 확보 시 승격).
_EVENT_RULES = (
    # --- KRX 시장조치 (Level A) ---
    (("불성실공시법인지정",), "unfaithful_disclosure", "krx", "A", "HIGH", 4, -4, "불성실공시법인 지정"),
    (("관리종목지정",), "management_issue", "krx", "A", "HIGH", 4, -4, "관리종목 지정"),
    (("거래정지",), "trading_halt", "krx", "A", "HIGH", 4, -4, "거래정지"),
    (("상장적격성",), "delisting_review", "krx", "A", "HIGH", 5, -5, "상장적격성 실질심사"),
    (("상장폐지",), "delisting_risk", "krx", "A", "HIGH", 5, -5, "상장폐지 관련 공시"),

    # --- DART 공시 (Level A) ---
    (("횡령",), "embezzlement", "dart", "A", "HIGH", 5, -5, "횡령 발생"),
    (("배임",), "breach_of_trust", "dart", "A", "HIGH", 5, -5, "배임 발생"),
    (("회생절차",), "rehabilitation", "dart", "A", "HIGH", 5, -5, "회생절차 개시"),
    (("감자결정",), "capital_reduction", "dart", "A", "HIGH", 4, -4, "감자 결정"),
    # ponytail: DART report_nm 은 보통 "감사보고서제출"뿐 의견 유형은 본문에만 있음 -> 실제 매치는 드묾(정직한 한계).
    (("감사의견거절", "감사의견부적정"), "audit_opinion_adverse", "dart", "A", "HIGH", 5, -5, "감사의견 부적정·거절"),
    (("감사의견한정",), "audit_opinion_qualified", "dart", "A", "HIGH", 4, -4, "감사의견 한정"),
    (("최대주주변경",), "major_shareholder_change", "dart", "A", "HIGH", 4, -2, "최대주주 변경"),
    (("전환사채권발행결정",), "cb_issue", "dart", "A", "HIGH", 3, -2, "전환사채(CB) 발행"),
    (("신주인수권부사채권발행결정",), "bw_issue", "dart", "A", "HIGH", 3, -2, "신주인수권부사채(BW) 발행"),
    (("유상증자결정",), "capital_increase", "dart", "A", "HIGH", 3, -2, "유상증자"),
    (("무상증자결정",), "rights_issue_free", "dart", "A", "HIGH", 2, None, "무상증자 결정"),
    (("자기주식소각",), "treasury_stock_retire", "dart", "A", "HIGH", 4, 4, "자사주 소각"),
    (("자기주식취득",), "treasury_stock_buy", "dart", "A", "HIGH", 2, 2, "자사주 취득"),
    (("현금·현물배당결정", "현금배당결정", "현물배당결정"), "dividend", "dart", "A", "HIGH", 2, None,
     "배당 결정(확대·축소 여부는 원문 확인)"),

    # --- Level B: 제목 키워드 기반(참고 표시, Thesis Score 미반영) ---
    (("단일판매공급계약체결",), "contract", "dart", "B", "MEDIUM", 2, 3, "대규모 공급계약"),
    (("시설투자", "생산설비", "투자결정"), "facility_investment", "dart", "B", "MEDIUM", 2, 2, "시설투자"),
    (("합병",), "merger", "dart", "B", "MEDIUM", 2, None, "합병"),
    (("분할",), "split", "dart", "B", "MEDIUM", 2, None, "분할"),
    (("신규사업",), "new_business", "dart", "B", "MEDIUM", 2, 2, "신규사업 진출"),

    # --- Level C: 시장경보성(참고만, Score 계산 대상 아님) ---
    (("투자주의",), "investment_caution", "krx", "C", "LOW", 1, None, "투자주의 지정"),
    (("투자유의",), "investment_alert", "krx", "C", "LOW", 1, None, "투자유의 지정"),
    (("단기과열",), "short_term_overheating", "krx", "C", "LOW", 1, None, "단기과열 지정"),
    (("투자경고",), "investment_warning", "krx", "C", "LOW", 1, None, "투자경고 지정"),
)

UNFAITHFUL_KW = "불성실공시법인지정"   # 지정 사유·벌점은 OpenDART 구조화 API에 없음 -> 원문 링크로 대체(dart_link)

# 스크리너 랭킹 점수(가점/감점/제외)용 event_type 묶음. Thesis Impact Score 와는 별개 개념.
HARD_EXCLUDE_TYPES = {  # 신규 후보 제외급(기존 HARD_NEGATIVE_KW 대응)
    "embezzlement", "breach_of_trust", "rehabilitation", "capital_reduction",
    "audit_opinion_adverse", "audit_opinion_qualified",
    "unfaithful_disclosure", "management_issue", "delisting_review", "delisting_risk", "trading_halt",
}
SOFT_PENALTY_TYPES = {"capital_increase", "cb_issue", "bw_issue", "major_shareholder_change"}
POSITIVE_BONUS_TYPES = {"treasury_stock_buy", "treasury_stock_retire", "contract"}


def dart_link(rcept_no: str):
    """공시 원문 뷰어 링크. rcept_no 없으면 None."""
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else None


def classify_event(report_nm: str):
    """공시 제목 -> 이벤트 taxonomy dict. 미매칭이면 None.

    반환: {event_type, category(dart/krx), level(A/B/C), confidence, severity, impact_score, reason}
    """
    nm = report_nm or ""
    for kws, event_type, category, level, confidence, severity, impact_score, reason in _EVENT_RULES:
        if any(kw in nm for kw in kws):
            return {
                "event_type": event_type, "category": category, "level": level,
                "confidence": confidence, "classification": ("KRX" if category == "krx" else "DART"),
                "severity": severity, "impact_score": impact_score, "reason": reason,
            }
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
    """기간 내 공시를 분류해 {"dart": {event_type: [...]}, "krx": {event_type: [...]}} 반환.
    DART 공시와 KRX 시장조치는 최상위 키로 반드시 분리(합치지 않음).
    각 항목은 {report_nm, rcept_dt, rcept_no, dart_link, level, confidence, classification,
    severity, impact_score, reason}. 조회 자체가 실패하면 **None**(disclosures 참조)."""
    items = disclosures(corp_code, bgn_de, end_de)
    if items is None:
        return None
    out = {"dart": {}, "krx": {}}
    for it in items:
        ev = classify_event(it.get("report_nm") or "")
        if not ev:
            continue
        rcept_no = it.get("rcept_no")
        bucket = out[ev["category"]].setdefault(ev["event_type"], [])
        bucket.append({
            "report_nm": it.get("report_nm"),
            "rcept_dt": it.get("rcept_dt"),
            "rcept_no": rcept_no,
            "dart_link": dart_link(rcept_no),
            "event_type": ev["event_type"],
            "level": ev["level"], "confidence": ev["confidence"], "classification": ev["classification"],
            "severity": ev["severity"], "impact_score": ev["impact_score"], "reason": ev["reason"],
        })
    return out


def level_a_events(flags: dict):
    """flags(dart+krx 통합) 중 Level A(Thesis Impact Score 산정 대상) 이벤트 평탄화 리스트."""
    out = []
    for cat in ("dart", "krx"):
        for items in (flags.get(cat) or {}).values():
            out.extend(it for it in items if it.get("level") == "A")
    return out


def event_types_present(flags: dict) -> set:
    """flags 안에 등장한 모든 event_type 집합(dart+krx 통합). 스크리너 랭킹 가/감점 판정용."""
    types = set()
    for cat in ("dart", "krx"):
        types |= set((flags.get(cat) or {}).keys())
    return types


def unfaithful_repeat_count(corp_code: str, bgn_de: str, end_de: str, max_pages: int = 30):
    """기간 내 '불성실공시법인지정' 등장 횟수(페이지네이션 처리).

    [주의] 지정 사유·벌점은 OpenDART에 구조화 필드가 없어 여기서 산출하지 않는다
    (document.xml 원문 자유텍스트뿐 -> 회사마다 포맷 달라 파싱 신뢰도 낮음. 원문 링크로 대체).
    조회 자체가 실패하면 None(모름), 정상 조회인데 0건이면 0(이번 건 제외한 과거 반복 없음)."""
    key = _key()
    if not key or not corp_code:
        return None
    count = 0
    page = 1
    while page <= max_pages:
        try:
            r = requests.get(f"{BASE}/list.json", params={
                "crtfc_key": key, "corp_code": corp_code,
                "bgn_de": bgn_de, "end_de": end_de,
                "page_no": page, "page_count": 100,
            }, timeout=30)
            d = r.json()
        except Exception:
            return None
        if d.get("status") == "013":
            break
        if d.get("status") != "000":
            return None
        items = d.get("list") or []
        count += sum(1 for it in items if UNFAITHFUL_KW in (it.get("report_nm") or ""))
        total_page = int(d.get("total_page") or 1)
        if page >= total_page:
            break
        page += 1
    return count


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
