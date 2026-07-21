"""工业制造领域预置知识加载与格式化。

从 data/manufacturing/*.json 加载故障码、设备参数、工艺标准、维护规则，
并提供格式化为 LLM 可消费文本的工具函数。
"""

import json
import os
from functools import lru_cache
from typing import Optional

from app.core.logging import setup_logger

logger = setup_logger("agents.manufacturing.knowledge")

# 数据目录（相对于项目根）
_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "manufacturing"
)


@lru_cache(maxsize=1)
def _load_fault_codes() -> list[dict]:
    """加载故障码知识库。"""
    path = os.path.join(_DATA_DIR, "fault_codes.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        codes = data.get("fault_codes", [])
        logger.info("故障码知识库加载成功: %d 条", len(codes))
        return codes
    except Exception as e:
        logger.warning("故障码知识库加载失败: %s", e)
        return []


@lru_cache(maxsize=1)
def _load_equipment_specs() -> list[dict]:
    """加载设备参数规格库。"""
    path = os.path.join(_DATA_DIR, "equipment_specs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        specs = data.get("equipment", [])
        logger.info("设备参数库加载成功: %d 台设备", len(specs))
        return specs
    except Exception as e:
        logger.warning("设备参数库加载失败: %s", e)
        return []


@lru_cache(maxsize=1)
def _load_process_standards() -> list[dict]:
    """加载工艺参数标准库。"""
    path = os.path.join(_DATA_DIR, "process_standards.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        processes = data.get("processes", [])
        logger.info("工艺标准库加载成功: %d 种工艺", len(processes))
        return processes
    except Exception as e:
        logger.warning("工艺标准库加载失败: %s", e)
        return []


@lru_cache(maxsize=1)
def _load_maintenance_rules() -> list[dict]:
    """加载维护规则库。"""
    path = os.path.join(_DATA_DIR, "maintenance_rules.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("maintenance_rules", [])
        logger.info("维护规则库加载成功: %d 条规则", len(rules))
        return rules
    except Exception as e:
        logger.warning("维护规则库加载失败: %s", e)
        return []


@lru_cache(maxsize=1)
def _load_health_rules() -> dict:
    """加载健康评估规则。"""
    path = os.path.join(_DATA_DIR, "maintenance_rules.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("health_assessment_rules", {})
    except Exception:
        return {}


# ============================================================
# 查询接口
# ============================================================

def search_fault_codes(keyword: str = "") -> list[dict]:
    """根据关键词搜索故障码（支持故障码/名称/类别/症状模糊匹配）。"""
    codes = _load_fault_codes()
    if not keyword:
        return codes
    keyword_lower = keyword.lower()
    results = []
    for item in codes:
        searchable = f"{item.get('code', '')} {item.get('name', '')} {item.get('category', '')} {item.get('symptom', '')}".lower()
        if keyword_lower in searchable:
            results.append(item)
    return results


def search_equipment_specs(keyword: str = "") -> list[dict]:
    """根据关键词搜索设备参数。"""
    specs = _load_equipment_specs()
    if not keyword:
        return specs
    keyword_lower = keyword.lower()
    results = []
    for item in specs:
        searchable = f"{item.get('model', '')} {item.get('name', '')} {item.get('category', '')}".lower()
        if keyword_lower in searchable:
            results.append(item)
    return results


def search_process_standards(keyword: str = "") -> list[dict]:
    """根据关键词搜索工艺标准。"""
    processes = _load_process_standards()
    if not keyword:
        return processes
    keyword_lower = keyword.lower()
    results = []
    for item in processes:
        searchable = f"{item.get('process_id', '')} {item.get('name', '')} {item.get('category', '')}".lower()
        if keyword_lower in searchable:
            results.append(item)
    return results


def search_maintenance_rules(keyword: str = "") -> list[dict]:
    """根据关键词搜索维护规则。"""
    rules = _load_maintenance_rules()
    if not keyword:
        return rules
    keyword_lower = keyword.lower()
    results = []
    for item in rules:
        searchable = f"{item.get('rule_id', '')} {item.get('equipment_type', '')} {item.get('level', '')}".lower()
        if keyword_lower in searchable:
            results.append(item)
    return results


# ============================================================
# 格式化为 LLM 可消费文本
# ============================================================

def format_fault_code(fault: dict) -> str:
    """将单条故障码格式化为文本。"""
    parts = [
        f"故障码: {fault.get('code', 'N/A')}",
        f"名称: {fault.get('name', 'N/A')}",
        f"类别: {fault.get('category', 'N/A')}",
        f"适用设备: {fault.get('equipment', '通用')}",
        f"故障现象: {fault.get('symptom', '')}",
        f"可能原因: {', '.join(fault.get('causes', []))}",
        f"维修步骤: {' → '.join(fault.get('repair_steps', []))}",
        f"所需备件: {', '.join(fault.get('parts', []))}",
        f"严重程度: {fault.get('severity', 'medium')}",
        f"安全提示: {fault.get('safety_note', '')}",
    ]
    return "\n".join(parts)


def format_equipment_spec(spec: dict) -> str:
    """将设备参数格式化为文本。"""
    parts = [
        f"设备型号: {spec.get('model', 'N/A')}",
        f"设备名称: {spec.get('name', 'N/A')}",
        f"类别: {spec.get('category', 'N/A')}",
        "额定参数:",
    ]
    for name, param in spec.get("rated_params", {}).items():
        parts.append(f"  - {name}: {param.get('value')}{param.get('unit', '')} (最大: {param.get('max')}{param.get('unit', '')})")
    parts.append("告警阈值:")
    for name, threshold in spec.get("alarm_thresholds", {}).items():
        parts.append(f"  - {name}: 预警 {threshold.get('warning')}{threshold.get('unit', '')} / 报警 {threshold.get('alarm')}{threshold.get('unit', '')}")
    cycle = spec.get("maintenance_cycle", {})
    if cycle:
        parts.append(f"维护周期: 日常 {cycle.get('日常保养', 'N/A')}h / 一级 {cycle.get('一级保养', 'N/A')}h / 二级 {cycle.get('二级保养', 'N/A')}h")
    return "\n".join(parts)


def format_process_standard(process: dict) -> str:
    """将工艺标准格式化为文本。"""
    parts = [
        f"工艺名称: {process.get('name', 'N/A')}",
        f"类别: {process.get('category', 'N/A')}",
        "标准参数:",
    ]
    for name, param in process.get("parameters", {}).items():
        parts.append(
            f"  - {name}: 范围 [{param.get('min')}~{param.get('max')}] 最优 {param.get('optimal')} {param.get('unit', '')} ({param.get('note', '')})"
        )
    defects = process.get("common_defects", {})
    if defects:
        parts.append("常见缺陷:")
        for name, info in defects.items():
            parts.append(f"  - {name}: 原因={info.get('cause', '')} | 对策={info.get('solution', '')}")
    return "\n".join(parts)


def format_maintenance_rule(rule: dict) -> str:
    """将维护规则格式化为文本。"""
    parts = [
        f"维护级别: {rule.get('level', 'N/A')}",
        f"适用设备: {rule.get('equipment_type', '通用')}",
        f"周期: 每 {rule.get('interval_hours', 'N/A')} 小时",
        f"预计耗时: {rule.get('estimated_time_min', 'N/A')} 分钟",
        "保养项目:",
    ]
    for i, item in enumerate(rule.get("items", []), 1):
        parts.append(f"  {i}. {item}")
    tools = rule.get("tools", [])
    if tools:
        parts.append(f"所需工具: {', '.join(tools)}")
    return "\n".join(parts)


def get_health_assessment_rules() -> str:
    """获取健康评估规则文本。"""
    rules = _load_health_rules()
    if not rules:
        return ""
    parts = ["设备健康度评估标准:"]
    scoring = rules.get("scoring", {})
    for level, info in scoring.items():
        r = info.get("range", [0, 0])
        parts.append(f"  - {info.get('label', level)} ({r[0]}-{r[1]}分): {info.get('action', '')}")
    factors = rules.get("degradation_factors", [])
    if factors:
        parts.append("退化权重因子:")
        for f in factors:
            parts.append(f"  - {f.get('factor', '')}: {f.get('weight', 0)*100:.0f}%")
    return "\n".join(parts)
