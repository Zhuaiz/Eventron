"""Traditional → Simplified Chinese normalization for event domain terms.

Pure utility — no DB, no HTTP.  Only normalizes *domain vocabulary*
(venue labels, role names, zone names, row/column headers).
Personal names are **never** touched.

Strategy: a curated mapping table for event-domain characters.
This avoids pulling in a full t2s library while covering 99 % of
real-world venue / seating data.
"""

from __future__ import annotations

# ── Domain-scoped T→S character map ──────────────────────────
# Only characters that actually appear in venue / seating / event
# vocabulary.  Kept intentionally small so it never corrupts names
# that happen to share a character with a different simplified form.

_T2S: dict[str, str] = {
    # Venue / seating
    "觀": "观",
    "眾": "众",
    "賓": "宾",
    "貴": "贵",
    "區": "区",
    "場": "场",
    "會": "会",
    "廳": "厅",
    "樓": "楼",
    "層": "层",
    "號": "号",
    "臺": "台",
    # Rows / columns / seating
    "排": "排",  # same in both
    "列": "列",  # same in both
    "個": "个",
    "張": "张",  # (as counter, not surname)
    "裏": "里",
    "間": "间",
    "門": "门",
    # Roles / titles
    "嘉": "嘉",  # same
    "員": "员",
    "師": "师",
    "導": "导",
    "領": "领",
    "長": "长",
    "總": "总",
    "務": "务",
    "記": "记",
    "辦": "办",
    "處": "处",
    "開": "开",
    "講": "讲",
    "發": "发",
    "職": "职",
    "團": "团",
    "組": "组",
    "議": "议",
    "報": "报",
    "與": "与",
    # Common event terms
    "簽": "签",
    "歡": "欢",
    "禮": "礼",
    "慶": "庆",
    "動": "动",
    "電": "电",
    "視": "视",
    "網": "网",
    "聯": "联",
    "響": "响",
    "設": "设",
    "備": "备",
    "計": "计",
    "畫": "画",
}

# Build reverse map (simplified form → set of traditional forms that map to it)
# for quick lookup
_S2T_REVERSE: dict[str, set[str]] = {}
for _t, _s in _T2S.items():
    _S2T_REVERSE.setdefault(_s, set()).add(_t)

# ── Curated whole-word term map (highest priority) ───────────
# Catches multi-character terms where char-by-char conversion
# might be ambiguous or incomplete.
_TERM_MAP: dict[str, str] = {
    "觀眾": "观众",
    "觀眾席": "观众席",
    "貴賓": "贵宾",
    "貴賓區": "贵宾区",
    "貴賓席": "贵宾席",
    "貴賓室": "贵宾室",
    "嘉賓": "嘉宾",
    "嘉賓區": "嘉宾区",
    "嘉賓席": "嘉宾席",
    "來賓": "来宾",
    "主講": "主讲",
    "主講人": "主讲人",
    "演講": "演讲",
    "演講嘉賓": "演讲嘉宾",
    "會議": "会议",
    "會場": "会场",
    "開幕": "开幕",
    "閉幕": "闭幕",
    "報到": "报到",
    "簽到": "签到",
    "歡迎": "欢迎",
    "頒獎": "颁奖",
    "舞臺": "舞台",
    "講臺": "讲台",
    "背景墻": "背景墙",
    "背景牆": "背景墙",
    "通道": "通道",
    "走道": "走道",
    "工作人員": "工作人员",
    "參會者": "参会者",
    "參加者": "参加者",
    "組織者": "组织者",
    "主辦": "主办",
    "協辦": "协办",
    "第一列": "第一列",
    "第一排": "第一排",
}


def normalize_event_term(text: str) -> str:
    """Normalize a short event-domain string (zone name, role, label).

    Applies whole-word substitution first, then character-level T→S
    for any remaining traditional characters.

    Personal names should NOT be passed to this function.

    Examples:
        >>> normalize_event_term("觀眾席")
        '观众席'
        >>> normalize_event_term("貴賓區")
        '贵宾区'
        >>> normalize_event_term("工作人員")
        '工作人员'
    """
    if not text:
        return text

    result = text.strip()

    # Pass 1: whole-word term replacement (longest match first)
    for trad, simp in sorted(
        _TERM_MAP.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        result = result.replace(trad, simp)

    # Pass 2: character-level fallback
    chars = list(result)
    for i, ch in enumerate(chars):
        if ch in _T2S:
            chars[i] = _T2S[ch]
    return "".join(chars)


def normalize_role(role: str | None) -> str:
    """Normalize an attendee role label to simplified Chinese.

    Returns a sensible default if role is empty/None.

    Examples:
        >>> normalize_role("觀眾")
        '观众'
        >>> normalize_role(None)
        '参会者'
        >>> normalize_role("")
        '参会者'
    """
    if not role or not role.strip():
        return "参会者"
    return normalize_event_term(role)


def normalize_zone(zone: str | None) -> str | None:
    """Normalize a zone/area label to simplified Chinese.

    Returns None if zone is empty/None.

    Examples:
        >>> normalize_zone("貴賓區")
        '贵宾区'
        >>> normalize_zone(None) is None
        True
    """
    if not zone or not zone.strip():
        return None
    return normalize_event_term(zone)


def infer_role_from_area_name(area_name: str) -> str:
    """Derive an attendee role from the area/sheet name.

    Heuristics:
    - Contains 贵宾/vip → "贵宾"
    - Contains 嘉宾 → "嘉宾"
    - Contains 观众 → "观众"
    - Contains 工作/staff → "工作人员"
    - Contains 演讲/speaker → "演讲嘉宾"
    - Otherwise → "参会者"

    Examples:
        >>> infer_role_from_area_name("貴賓區")
        '贵宾'
        >>> infer_role_from_area_name("觀眾席")
        '观众'
        >>> infer_role_from_area_name("VIP Room")
        '贵宾'
    """
    norm = normalize_event_term(area_name).lower()
    if "贵宾" in norm or "vip" in norm:
        return "贵宾"
    # Check speaker before generic 嘉宾 (演讲嘉宾 contains 嘉宾)
    if "演讲" in norm or "speaker" in norm:
        return "演讲嘉宾"
    if "主讲" in norm or "讲师" in norm:
        return "演讲嘉宾"
    if "嘉宾" in norm:
        return "嘉宾"
    if "观众" in norm:
        return "观众"
    if "工作" in norm or "staff" in norm:
        return "工作人员"
    return "参会者"


def clean_name(raw: str | None) -> str | None:
    """Clean an attendee name: strip whitespace, collapse inner spaces.

    Does NOT do T→S conversion — names are kept as-is.

    Examples:
        >>> clean_name("陳 旭")
        '陳旭'
        >>> clean_name("  Julian Gaetner  ")
        'Julian Gaetner'
        >>> clean_name(None) is None
        True
    """
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    # For CJK names, remove inner spaces (陳 旭 → 陳旭)
    # For Western names, keep single spaces (Julian Gaetner stays)
    # Heuristic: if most chars are CJK, remove all spaces
    cjk_count = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    if cjk_count > len(s.replace(" ", "")) * 0.5:
        return s.replace(" ", "")
    # Western name: collapse multiple spaces
    return " ".join(s.split())
