#!/usr/bin/env python3
"""
lunar_calendar.py — 한국 음력 공휴일 즉답 유틸리티
사용: python3 tools/lunar_calendar.py [YYYY]
의존: lunardate (pip3 install lunardate)
"""
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional
from lunardate import LunarDate


# 음력 기준 주요 공휴일 (월, 일, 연휴_전_일수, 연휴_후_일수, 이름)
LUNAR_HOLIDAYS = [
    (1, 1, 1, 1, "설날"),       # 음력 1/1, 앞뒤 하루씩
    (4, 8, 0, 0, "부처님오신날"),  # 음력 4/8
    (7, 7, 0, 0, "칠석"),        # 참고용 (비공휴일)
    (8, 15, 1, 1, "추석"),       # 음력 8/15, 앞뒤 하루씩
]


def lunar_to_solar(year: int, month: int, day: int) -> date:
    return LunarDate(year, month, day).to_solar_date()


def get_holidays(year: int) -> List[Dict]:
    """양력 연도 기준 주요 음력 공휴일 목록 반환."""
    results = []
    for l_month, l_day, before, after, name in LUNAR_HOLIDAYS:
        try:
            solar = lunar_to_solar(year, l_month, l_day)
        except Exception:
            # 음력 날짜가 해당 연도에 없을 경우 (윤달 등) 스킵
            continue
        results.append({"name": name, "date": solar, "lunar": f"음력 {l_month}/{l_day}"})
        if before:
            d = solar - timedelta(days=before)
            ld = LunarDate.from_solar_date(d.year, d.month, d.day)
            results.append({
                "name": f"{name} 전날",
                "date": d,
                "lunar": f"음력 {ld.month}/{ld.day}",
            })
        if after:
            d = solar + timedelta(days=after)
            ld = LunarDate.from_solar_date(d.year, d.month, d.day)
            results.append({
                "name": f"{name} 다음날",
                "date": d,
                "lunar": f"음력 {ld.month}/{ld.day}",
            })
    results.sort(key=lambda x: x["date"])
    return results


def days_until(target: date, from_date: Optional[date] = None) -> int:
    base = from_date or date.today()
    return (target - base).days


def next_holiday(from_date: Optional[date] = None) -> Optional[Dict]:
    """오늘 이후 가장 가까운 공휴일 반환."""
    base = from_date or date.today()
    for year in (base.year, base.year + 1):
        for h in get_holidays(year):
            if h["date"] >= base:
                return {**h, "days_left": days_until(h["date"], base)}
    return None


def solar_to_lunar(solar: date) -> str:
    """양력 → 음력 문자열 변환."""
    ld = LunarDate.from_solar_date(solar.year, solar.month, solar.day)
    leap = " (윤달)" if ld.isLeapMonth else ""
    return f"음력 {ld.year}/{ld.month:02d}/{ld.day:02d}{leap}"


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
    print(f"\n📅 {year}년 주요 음력 공휴일\n{'─'*35}")
    for h in get_holidays(year):
        d = h["date"]
        left = days_until(d)
        tag = f"  ← D{left:+d}" if abs(left) <= 30 else ""
        print(f"  {d.strftime('%m/%d')} ({d.strftime('%a')})  {h['name']:<12} [{h['lunar']}]{tag}")

    print(f"\n✦ 다음 공휴일:")
    nxt = next_holiday()
    if nxt:
        print(f"  {nxt['name']} — {nxt['date']} (D{nxt['days_left']:+d})")

    # 오늘 음력
    today = date.today()
    print(f"\n  오늘 {today} = {solar_to_lunar(today)}\n")


if __name__ == "__main__":
    main()
