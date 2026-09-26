"""环境监控接口：维护环境记录，覆盖确认采集、登记缺测、提交校准等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.environment import EnvironmentService

router = APIRouter(prefix="/api/environment", tags=["环境监控"])

service = EnvironmentService()

LIST_FIELDS = ["记录编号", "监控区域", "温度值", "湿度值", "压差值", "采集时间", "记录人员", "监控状态"]
STATUSES = ["正常采集", "数据缺测", "超限报警", "已校准"]


@router.get("/stats")
def environment_stats() -> dict[str, Any]:
    """环境监控统计：在监区域、超限次数、缺测记录数，以及今日缺测区域的可读说明。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出环境监控清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "environment", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    area: str | None = Query(default=None, description="按监控区域检索"),
    status: str | None = Query(default=None, description="正常采集、数据缺测、超限报警、已校准"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号、监控区域与状态过滤环境监控列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, area=area, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条环境记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"环境记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条环境记录：缺字段、重复编号都会说明原因；重复提交不会覆盖缺测标记。

    温度或湿度超限时直接标记为超限报警，消息里写清是哪项读数超限。
    """
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条环境记录执行确认采集、登记缺测、提交校准；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
