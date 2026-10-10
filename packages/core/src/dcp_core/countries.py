"""账单国家 / 出口地区 / 币种。界面选项与建单请求共用。"""

from __future__ import annotations

from typing import Dict, List, Tuple

# code, 中文名, 币种, 语言
REGIONS: List[Tuple[str, str, str, str]] = [
    ("US", "美国", "USD", "en-US"),
    ("PH", "菲律宾", "PHP", "en-PH"),
    ("CL", "智利", "CLP", "es-CL"),
    ("EG", "埃及", "EGP", "ar-EG"),
    ("JP", "日本", "JPY", "ja-JP"),
    ("GB", "英国", "GBP", "en-GB"),
    ("TR", "土耳其", "TRY", "tr-TR"),
    ("BR", "巴西", "BRL", "pt-BR"),
    ("MX", "墨西哥", "MXN", "es-MX"),
    ("IN", "印度", "INR", "en-IN"),
    ("ID", "印尼", "IDR", "id-ID"),
    ("VN", "越南", "VND", "vi-VN"),
    ("TH", "泰国", "THB", "th-TH"),
    ("MY", "马来西亚", "MYR", "en-MY"),
    ("SG", "新加坡", "SGD", "en-SG"),
    ("KR", "韩国", "KRW", "ko-KR"),
    ("AU", "澳大利亚", "AUD", "en-AU"),
    ("CA", "加拿大", "CAD", "en-CA"),
    ("DE", "德国", "EUR", "de-DE"),
    ("NL", "荷兰", "EUR", "nl-NL"),
    ("PL", "波兰", "PLN", "pl-PL"),
    ("AR", "阿根廷", "ARS", "es-AR"),
    ("SA", "沙特", "SAR", "ar-SA"),
    ("AE", "阿联酋", "AED", "en-AE"),
    ("ZA", "南非", "ZAR", "en-ZA"),
]

_BY_CODE: Dict[str, Tuple[str, str, str, str]] = {row[0]: row for row in REGIONS}


def normalize_country(code: str) -> str:
    return str(code or "").strip().upper()


def is_supported(code: str) -> bool:
    return normalize_country(code) in _BY_CODE


def currency_for(code: str) -> str:
    row = _BY_CODE.get(normalize_country(code))
    return row[2] if row else "USD"


def locale_for(code: str) -> str:
    row = _BY_CODE.get(normalize_country(code))
    return row[3] if row else "en-US"


_TZ = {
    "US": "America/New_York",
    "PH": "Asia/Manila",
    "CL": "America/Santiago",
    "EG": "Africa/Cairo",
    "JP": "Asia/Tokyo",
    "GB": "Europe/London",
    "TR": "Europe/Istanbul",
    "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City",
    "IN": "Asia/Kolkata",
    "ID": "Asia/Jakarta",
    "VN": "Asia/Ho_Chi_Minh",
    "TH": "Asia/Bangkok",
    "MY": "Asia/Kuala_Lumpur",
    "SG": "Asia/Singapore",
    "KR": "Asia/Seoul",
    "AU": "Australia/Sydney",
    "CA": "America/Toronto",
    "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam",
    "PL": "Europe/Warsaw",
    "AR": "America/Argentina/Buenos_Aires",
    "SA": "Asia/Riyadh",
    "AE": "Asia/Dubai",
    "ZA": "Africa/Johannesburg",
}


def timezone_for(code: str) -> str:
    return _TZ.get(normalize_country(code), "America/New_York")


def country_codes() -> List[str]:
    return [row[0] for row in REGIONS]


__all__ = [
    "REGIONS",
    "normalize_country",
    "is_supported",
    "currency_for",
    "locale_for",
    "timezone_for",
    "country_codes",
]
