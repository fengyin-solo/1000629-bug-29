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


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="正常采集、数据缺测、超限报警、已校准"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤环境监控列表；当天缺测的区域会以缺测行补出。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」无效，可选：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """统计卡片与各监控区域当前状态：口径与列表、详情一致。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出环境监控清单：返回当前数据口径下的全量记录。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "environment", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: str) -> dict[str, Any]:
    """读取单条环境记录明细（含 missing-<区域> 的当日缺测行）；不存在时给出可读说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"环境记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条环境记录；缺字段、数值非法或记录编号重复都会说明原因，且不落库。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        raise HTTPException(status_code=400, detail=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条环境记录执行确认采集、登记缺测、提交校准；不允许的动作会被拦下并说明原因。

    重复提交同一动作保持幂等，返回冲突提示，不会抹掉既有缺测/校准标记。
    """
    action = str(payload.values.get("action") or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="未指定要执行的动作，请选择确认采集、登记缺测或提交校准")
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        # 记录不存在 / 动作非法 / 重复提交：让前端拿到非 2xx，触发可读提示与重试入口
        not_found = "不存在" in message
        status_code = 404 if not_found else 409 if "重复" in message else 400
        raise HTTPException(status_code=status_code, detail=message)
    return ActionResult(ok=True, message=message, entry=entry)
