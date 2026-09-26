"""环境监控业务规则：状态口径、字段校验、缺测补录都收在这里。

列表、详情与统计共用 _present_row 的归一化结果，保证监控区域、温度值与湿度值
的状态在三处保持一致；本模块的规则不影响校准记录模块。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "environment"

# 实验室常规环境控制范围：温度 18~26℃，湿度 30~70%RH
TEMP_RANGE = (18.0, 26.0)
HUMIDITY_RANGE = (30.0, 70.0)

REQUIRED_FIELDS = ["记录编号", "监控区域", "温度值", "湿度值", "采集时间"]
OPTIONAL_FIELDS = ["压差值", "记录人员"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

STATUS_NORMAL = "正常采集"
STATUS_MISSING = "数据缺测"
STATUS_OVER = "超限报警"
STATUS_CALIBRATED = "已校准"

# 人工动作设置的状态优先于数值推导，校准结论不会被后续读数覆盖
EXPLICIT_STATUSES = {STATUS_MISSING, STATUS_CALIBRATED}
ACTION_RULES = {
    "确认采集": STATUS_NORMAL,
    "登记缺测": STATUS_MISSING,
    "提交校准": STATUS_CALIBRATED,
}

STATE_NORMAL = "正常"
STATE_OVER = "超限"
STATE_MISSING = "缺测"
STATE_ABSENT = "缺失"


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _to_float(value: Any) -> float | None:
    """空值返回 None；无法解析为数值时抛 ValueError，由调用方给出可读说明。"""
    if _is_blank(value):
        return None
    try:
        return round(float(str(value).strip()), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(value)) from exc


def _measure_state(value: Any, low: float, high: float, unit: str) -> tuple[str, float | None, str | None]:
    """返回（字段状态, 数值, 说明）；必填测量项缺失即为缺测，越界即为超限。"""
    if _is_blank(value):
        return STATE_MISSING, None, None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return STATE_MISSING, None, f"数值无法识别（{value!r}），按缺测处理"
    if number < low or number > high:
        return (
            STATE_OVER,
            number,
            f"{number:g}{unit} 超出允许范围 {low:g}~{high:g}{unit}",
        )
    return STATE_NORMAL, number, None


def _derive_status(temp_state: str, hum_state: str) -> str:
    if STATE_OVER in (temp_state, hum_state):
        return STATUS_OVER
    if STATE_MISSING in (temp_state, hum_state):
        return STATUS_MISSING
    return STATUS_NORMAL


def _present_row(row: dict[str, Any]) -> dict[str, Any]:
    """把存储行归一化成接口返回结构；同时回写 status/abnormal，保证存储口径一致。"""
    presented: dict[str, Any] = {"id": row.get("id")}
    for field in ALL_FIELDS:
        presented[field] = row.get(field)

    temp_state, _, temp_note = _measure_state(row.get("温度值"), *TEMP_RANGE, "℃")
    hum_state, _, hum_note = _measure_state(row.get("湿度值"), *HUMIDITY_RANGE, "%RH")
    if _is_blank(row.get("压差值")):
        dp_state = STATE_ABSENT
        dp_note = "压差值缺失，请及时补录"
    else:
        dp_state = STATE_NORMAL
        dp_note = None

    presented["温度状态"] = temp_state
    presented["湿度状态"] = hum_state
    presented["压差状态"] = dp_state

    stored_status = str(row.get("status") or "")
    pressure_missing_note = dp_note
    if stored_status in EXPLICIT_STATUSES:
        # 人工登记的缺测/校准结论优先，读数只做提示不改状态
        status = stored_status
        if status == STATUS_MISSING:
            # 整行已缺测时不再单列压差缺失，避免说明重复
            pressure_missing_note = None
    else:
        status = _derive_status(temp_state, hum_state)
    presented["status"] = status
    presented["abnormal"] = status in (STATUS_OVER, STATUS_MISSING)
    presented["pending"] = status != STATUS_CALIBRATED
    notes = [note for note in (temp_note, hum_note, pressure_missing_note) if note]
    presented["说明"] = "；".join(notes)
    presented["missing_today"] = False

    row["status"] = status
    row["abnormal"] = presented["abnormal"]
    row["pending"] = presented["pending"]
    return presented


def _missing_row(area: str, today: str) -> dict[str, Any]:
    """监控区域当天没有任何采集记录时，补一条虚拟缺测行提示补录。"""
    return {
        "id": f"missing-{area}",
        "记录编号": None,
        "监控区域": area,
        "温度值": None,
        "湿度值": None,
        "压差值": None,
        "采集时间": today,
        "记录人员": None,
        "status": STATUS_MISSING,
        "abnormal": True,
        "pending": True,
        "温度状态": STATE_MISSING,
        "湿度状态": STATE_MISSING,
        "压差状态": STATE_ABSENT,
        "说明": f"该监控区域今日（{today}）无采集数据，按缺测处理，请尽快补录",
        "missing_today": True,
    }


class EnvironmentService:
    # -- 列表与详情 --------------------------------------------------------

    def _presented_rows(self) -> list[dict[str, Any]]:
        today = date.today().isoformat()
        rows = [_present_row(row) for row in store.rows(MODULE)]

        known_areas = {str(row.get("监控区域") or "").strip() for row in rows}
        known_areas.discard("")
        areas_today = {
            str(row.get("监控区域") or "").strip()
            for row in rows
            if str(row.get("采集时间") or "").strip() == today
        }
        for area in sorted(known_areas - areas_today):
            rows.append(_missing_row(area, today))

        rows.sort(key=lambda row: (str(row.get("采集时间") or ""), str(row.get("id"))), reverse=True)
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._presented_rows()
        if keyword:
            key = keyword.strip()
            rows = [row for row in rows if key in str(row.get("记录编号") or "")]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """支持数字主键与 missing-<区域> 形式的当日缺测行。"""
        identifier = entry_id.strip()
        if identifier.startswith("missing-"):
            area = identifier.removeprefix("missing-")
            for row in self._presented_rows():
                if row.get("missing_today") and row.get("监控区域") == area:
                    return row
            return None
        try:
            numeric_id = int(identifier)
        except (TypeError, ValueError):
            return None
        row = store.find(MODULE, numeric_id)
        return _present_row(row) if row is not None else None

    # -- 统计 --------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """统计卡片与区域状态明细，口径与列表、详情完全一致。"""
        rows = self._presented_rows()
        real_rows = [row for row in rows if not row.get("missing_today")]
        areas = {str(row.get("监控区域") or "").strip() for row in real_rows}
        over_count = sum(1 for row in rows if row.get("status") == STATUS_OVER)
        missing_count = sum(1 for row in rows if row.get("status") == STATUS_MISSING)

        # 每个区域取列表排序后的首条（当天优先），与列表里该区域今日展示行一致
        area_summary: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            area = str(row.get("监控区域") or "").strip()
            if not area or area in seen:
                continue
            seen.add(area)
            area_summary.append({
                "监控区域": area,
                "status": row.get("status"),
                "温度状态": row.get("温度状态"),
                "湿度状态": row.get("湿度状态"),
                "采集时间": row.get("采集时间"),
                "说明": row.get("说明"),
                "missing_today": bool(row.get("missing_today")),
            })

        if any(row.get("status") == STATUS_OVER for row in area_summary):
            area_overall = STATUS_OVER
        elif any(row.get("status") == STATUS_MISSING for row in area_summary):
            area_overall = STATUS_MISSING
        elif area_summary:
            area_overall = STATUS_NORMAL
        else:
            area_overall = STATUS_MISSING

        return {
            "cards": [
                {"label": "在监区域", "value": len(areas), "status": area_overall},
                {"label": "超限次数", "value": over_count, "status": STATUS_OVER if over_count else STATUS_NORMAL},
                {"label": "缺测记录数", "value": missing_count, "status": STATUS_MISSING if missing_count else STATUS_NORMAL},
            ],
            "areas": area_summary,
        }

    # -- 登记与动作 --------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        cleaned: dict[str, Any] = {}
        missing: list[str] = []
        for field in REQUIRED_FIELDS:
            raw = values.get(field)
            if _is_blank(raw):
                missing.append(field)
            else:
                cleaned[field] = str(raw).strip()
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}，请补全后再提交"

        # 压差值可选：留空允许保存（列表会提示缺失），但填了就必须是数值
        pressure_raw = values.get("压差值")
        if not _is_blank(pressure_raw):
            try:
                cleaned["压差值"] = _to_float(pressure_raw)
            except ValueError:
                return None, f"压差值需要填写数值（单位 Pa），当前收到「{pressure_raw}」"

        for field, label, unit in (("温度值", "温度值", "℃"), ("湿度值", "湿度值", "%RH")):
            try:
                cleaned[field] = _to_float(cleaned[field])
            except ValueError:
                return None, f"{label}需要填写数值（单位 {unit}），当前收到「{cleaned[field]}」"

        operator = values.get("记录人员")
        if not _is_blank(operator):
            cleaned["记录人员"] = str(operator).strip()

        rows = store.rows(MODULE)
        code = cleaned["记录编号"]
        duplicate = next((row for row in rows if str(row.get("记录编号") or "").strip() == code), None)
        if duplicate is not None:
            # 重复提交不能新建，更不能把既有缺测标记冲掉
            return None, (
                f"记录编号「{code}」已存在（监控区域：{duplicate.get('监控区域') or '—'}，"
                f"采集时间：{duplicate.get('采集时间') or '—'}），重复提交会覆盖缺测标记，已拒绝；"
                "如需变更请在列表中对原记录执行动作"
            )

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            **cleaned,
        }
        rows.append(entry)
        return _present_row(entry), "环境记录已登记"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"环境记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于环境监控可执行范围"

        target = ACTION_RULES[action]
        current = str(entry.get("status") or "")
        if current == target:
            # 重复提交同一条动作保持幂等：不改状态、不抹掉缺测/校准标记
            return None, f"记录当前已是「{target}」状态，请勿重复提交，原有标记保持不变"

        entry["status"] = target
        presented = _present_row(entry)
        if action == "确认采集" and presented["status"] != STATUS_NORMAL:
            return presented, f"环境记录已{action}，但读数提示「{presented['status']}」，请核对温度与湿度"
        return presented, f"环境记录已{action}"
