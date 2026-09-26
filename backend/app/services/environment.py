"""环境监控业务规则：状态流转、字段校验、超限判定与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "environment"
REQUIRED_FIELDS = ["记录编号", "监控区域", "温度值", "采集时间"]
DISPLAY_FIELDS = ["记录编号", "监控区域", "温度值", "湿度值", "压差值", "采集时间", "记录人员", "监控状态"]
# 重复判定口径：同一记录编号且以下字段完全一致，视为同一条记录的重复提交
IDENTITY_FIELDS = ["记录编号", "监控区域", "温度值", "湿度值", "压差值", "采集时间"]
STATUS_ORDER = ["正常采集", "数据缺测", "超限报警", "已校准"]
ACTION_RULES = {"确认采集": "正常采集", "登记缺测": "数据缺测", "提交校准": "已校准"}
NEGATIVE_ACTIONS = ["登记缺测"]

# 温湿度限值：采集值超出区间即判定超限报警，可按实验室实际要求调整
TEMP_RANGE = (15.0, 28.0)
HUMIDITY_RANGE = (30.0, 70.0)

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_number(raw: Any) -> float | None:
    """从「26.5℃」「55%」这类读数里提取数值；取不到就当作未采集，不参与超限判定。"""
    match = _NUMBER_PATTERN.search(str(raw or ""))
    return float(match.group()) if match else None


def _over_limit_reasons(values: dict[str, Any]) -> list[str]:
    """返回超限原因；温度、湿度各自独立判断，可同时超限。"""
    reasons: list[str] = []
    temp = _parse_number(values.get("温度值"))
    if temp is not None and not TEMP_RANGE[0] <= temp <= TEMP_RANGE[1]:
        reasons.append(f"温度值 {temp:g}℃ 超出 {TEMP_RANGE[0]:g}–{TEMP_RANGE[1]:g}℃ 范围")
    humidity = _parse_number(values.get("湿度值"))
    if humidity is not None and not HUMIDITY_RANGE[0] <= humidity <= HUMIDITY_RANGE[1]:
        reasons.append(f"湿度值 {humidity:g}% 超出 {HUMIDITY_RANGE[0]:g}–{HUMIDITY_RANGE[1]:g}% 范围")
    return reasons


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """统一对外结构：补齐缺失字段、让「监控状态」与系统 status 保持一致。

    列表、详情、统计都从同一份 status 取值，避免三处口径不一致。
    """
    item = dict(row)
    for field in DISPLAY_FIELDS:
        item.setdefault(field, None)
    item["监控状态"] = str(row.get("status") or STATUS_ORDER[0])
    return item


class EnvironmentService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if area:
            rows = [row for row in rows if area in str(row.get("监控区域", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _present(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        rows = store.rows(MODULE)
        code = str(values.get("记录编号") or "").strip()
        existing = next(
            (row for row in rows if str(row.get("记录编号", "")).strip() == code),
            None,
        )
        if existing is not None:
            if self._same_reading(existing, values):
                # 幂等：同一条记录重复提交（例如超时后重试）直接返回原记录，缺测等标记保持不变
                return _present(existing), f"记录 {code} 已登记过，本次未重复写入"
            return None, (
                f"记录编号 {code} 已存在（当前状态：{existing.get('status')}），"
                "重复提交不会覆盖原有记录，请核对记录编号"
            )
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in DISPLAY_FIELDS})
        reasons = _over_limit_reasons(entry)
        if reasons:
            entry["status"] = "超限报警"
            entry["pending"] = True
            entry["abnormal"] = True
            message = f"环境记录已登记，但{'；'.join(reasons)}，已标记超限报警"
        else:
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            message = "环境记录已登记"
        entry["监控状态"] = entry["status"]
        rows.append(entry)
        return _present(entry), message

    @staticmethod
    def _same_reading(existing: dict[str, Any], values: dict[str, Any]) -> bool:
        return all(
            str(existing.get(field) or "").strip() == str(values.get(field) or "").strip()
            for field in IDENTITY_FIELDS
        )

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"环境记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于环境监控可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["监控状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _present(entry), f"环境记录已{action}"

    def stats(self) -> dict[str, Any]:
        """统计口径与列表、详情一致：同一份 status 聚合卡片，并给今日缺测区域可读说明。"""
        rows = store.rows(MODULE)
        areas = sorted({
            str(row.get("监控区域") or "").strip()
            for row in rows
            if str(row.get("监控区域") or "").strip()
        })
        today = date.today().isoformat()
        covered_today = {
            str(row.get("监控区域") or "").strip()
            for row in rows
            if str(row.get("采集时间") or "").strip().startswith(today)
        }
        return {
            "areas": len(areas),
            "over_limit": sum(1 for row in rows if row.get("status") == "超限报警"),
            "missing": sum(1 for row in rows if row.get("status") == "数据缺测"),
            "total": len(rows),
            "today": today,
            "missing_areas": [area for area in areas if area not in covered_today],
        }
