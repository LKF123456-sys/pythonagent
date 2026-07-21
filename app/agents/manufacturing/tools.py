"""工业智能制造领域工具：Function Calling 工具 + 节点直接调用函数。"""

import random
import re
from datetime import datetime

from langchain_core.tools import tool

from app.core.logging import setup_logger
from app.agents.manufacturing.knowledge import (
    format_equipment_spec,
    format_fault_code,
    format_maintenance_rule,
    format_process_standard,
    get_health_assessment_rules,
    search_equipment_specs,
    search_fault_codes,
    search_maintenance_rules,
    search_process_standards,
)

logger = setup_logger("agents.manufacturing.tools")


# ============================================================
# LangChain Function Calling 工具
# ============================================================

@tool
def query_fault_code(code: str) -> str:
    """查询工业设备故障码信息。输入故障码（如 E001）或关键词（如 过电流、振动），返回故障原因和维修方案。

    Args:
        code: 故障码或故障关键词
    """
    results = search_fault_codes(code)
    if not results:
        return f"未找到与 '{code}' 相关的故障码信息。"
    formatted = [format_fault_code(r) for r in results[:3]]
    return f"找到 {len(results)} 条相关故障信息：\n\n" + "\n\n---\n\n".join(formatted)


@tool
def query_equipment_params(model: str) -> str:
    """查询工业设备的额定参数和告警阈值。输入设备型号（如 CNC-VMC850）或设备类型关键词。

    Args:
        model: 设备型号或类型关键词
    """
    results = search_equipment_specs(model)
    if not results:
        return f"未找到与 '{model}' 相关的设备参数信息。"
    formatted = [format_equipment_spec(r) for r in results[:3]]
    return f"找到 {len(results)} 台相关设备：\n\n" + "\n\n---\n\n".join(formatted)


@tool
def simulate_sensor_data(equipment_type: str) -> str:
    """模拟工业设备传感器实时读数。输入设备类型（如 电机、液压站、空压机），返回模拟的温度/振动/压力等数据及状态评估。

    Args:
        equipment_type: 设备类型名称
    """
    return _generate_sensor_data(equipment_type)


@tool
def check_maintenance_schedule(equipment_type: str, running_hours: int = 1000) -> str:
    """查询设备维护计划和保养建议。输入设备类型和已运行小时数，返回应执行的维护项目。

    Args:
        equipment_type: 设备类型（如 旋转设备、液压系统、工业机器人、空压机）
        running_hours: 设备已运行小时数
    """
    rules = search_maintenance_rules(equipment_type)
    if not rules:
        rules = search_maintenance_rules("")  # 返回所有规则
    if not rules:
        return "未找到相关维护规则。"

    parts = [f"设备类型: {equipment_type}，已运行: {running_hours} 小时\n"]
    parts.append("维护计划建议：\n")

    for rule in rules[:4]:
        interval = rule.get("interval_hours", 0)
        level = rule.get("level", "")
        # 判断是否到期
        if interval > 0 and running_hours >= interval:
            status = "⚠️ 已到期" if running_hours >= interval * 1.2 else "📋 即将到期"
        else:
            remaining = interval - running_hours if interval > 0 else "N/A"
            status = f"✅ 剩余 {remaining}h"
        parts.append(f"- [{level}] 周期 {interval}h | 状态: {status}")
        parts.append(f"  项目: {', '.join(rule.get('items', [])[:3])}...")

    parts.append(f"\n{get_health_assessment_rules()}")
    return "\n".join(parts)


@tool
def analyze_process_params(process_name: str) -> str:
    """查询工业生产工艺参数标准。输入工艺名称（如 注塑、CNC铣削、焊接、SMT），返回标准参数范围和常见缺陷对策。

    Args:
        process_name: 工艺名称关键词
    """
    results = search_process_standards(process_name)
    if not results:
        return f"未找到与 '{process_name}' 相关的工艺标准。"
    formatted = [format_process_standard(r) for r in results[:2]]
    return f"找到 {len(results)} 种相关工艺：\n\n" + "\n\n---\n\n".join(formatted)


# 工业工具列表（供 bind_tools 使用）
MFG_TOOLS = [
    query_fault_code,
    query_equipment_params,
    simulate_sensor_data,
    check_maintenance_schedule,
    analyze_process_params,
]


# ============================================================
# 节点直接调用函数（非 LangChain tool，供 nodes.py 使用）
# ============================================================

def query_fault_code_by_text(text: str) -> str:
    """从用户问题文本中提取故障码并查询。"""
    # 尝试提取故障码模式（E001, e001, E-001 等）
    code_pattern = re.compile(r'[Ee][-_]?(\d{3,4})')
    match = code_pattern.search(text)
    if match:
        code = f"E{match.group(1)}"
        results = search_fault_codes(code)
        if results:
            return "\n\n".join(format_fault_code(r) for r in results[:2])

    # 无明确故障码时，用关键词搜索
    keywords = _extract_keywords(text)
    if keywords:
        results = search_fault_codes(keywords)
        if results:
            return "\n\n".join(format_fault_code(r) for r in results[:2])

    return ""


def simulate_sensor_by_text(text: str) -> str:
    """根据用户问题中的设备类型生成模拟传感器数据。"""
    equipment_type = _detect_equipment_type(text)
    return _generate_sensor_data(equipment_type)


def check_maintenance_by_text(text: str) -> str:
    """根据用户问题提取设备类型和运行时长，查询维护计划。"""
    equipment_type = _detect_equipment_type(text)
    # 尝试提取运行时长
    hours_match = re.search(r'(\d+)\s*(?:小时|h|hour)', text, re.IGNORECASE)
    running_hours = int(hours_match.group(1)) if hours_match else 1000

    rules = search_maintenance_rules(equipment_type)
    if not rules:
        return ""

    parts = []
    for rule in rules[:3]:
        parts.append(format_maintenance_rule(rule))
    return "\n\n---\n\n".join(parts)


def analyze_process_params_by_text(text: str) -> str:
    """根据用户问题中的工艺关键词查询工艺标准。"""
    process_keywords = ["注塑", "CNC", "铣削", "焊接", "SMT", "贴片", "切削", "成型"]
    for kw in process_keywords:
        if kw in text:
            results = search_process_standards(kw)
            if results:
                return "\n\n".join(format_process_standard(r) for r in results[:2])
    return ""


# 供路由层 REST 接口使用
def search_fault_codes_api(keyword: str) -> list[dict]:
    """故障码搜索（REST API 用）。"""
    return search_fault_codes(keyword)


def search_equipment_specs_api(keyword: str) -> list[dict]:
    """设备参数搜索（REST API 用）。"""
    return search_equipment_specs(keyword)


# ============================================================
# 辅助函数
# ============================================================

def _extract_keywords(text: str) -> str:
    """从文本中提取故障相关关键词。"""
    fault_keywords = [
        "过电流", "过电压", "过热", "振动", "泄漏", "压力不足",
        "通信中断", "伺服", "报警", "停机", "异响", "漏油",
        "温度高", "油温", "冷却", "润滑", "接地", "跳闸",
    ]
    found = [kw for kw in fault_keywords if kw in text]
    return found[0] if found else ""


def _detect_equipment_type(text: str) -> str:
    """从文本中检测设备类型。"""
    type_map = {
        "机器人": "工业机器人",
        "机械臂": "工业机器人",
        "液压": "液压系统",
        "空压机": "空压机",
        "压缩机": "空压机",
        "水泵": "离心水泵",
        "电机": "通用旋转设备",
        "CNC": "数控机床",
        "加工中心": "数控机床",
        "注塑机": "注塑设备",
    }
    for keyword, eq_type in type_map.items():
        if keyword in text:
            return eq_type
    return "通用旋转设备"


def _generate_sensor_data(equipment_type: str) -> str:
    """生成模拟传感器数据。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 根据设备类型生成不同的传感器数据
    sensor_configs = {
        "通用旋转设备": [
            ("轴承温度", 55, 85, "°C", 75),
            ("振动值", 1.5, 7.0, "mm/s", 4.5),
            ("电机电流", 15, 60, "A", 50),
            ("转速", 1400, 3000, "rpm", 2950),
        ],
        "液压系统": [
            ("油温", 35, 70, "°C", 55),
            ("系统压力", 5, 25, "MPa", 16),
            ("油液清洁度", 6, 12, "NAS", 8),
            ("泵出口流量", 20, 100, "L/min", 63),
        ],
        "工业机器人": [
            ("J1关节温度", 40, 80, "°C", 65),
            ("J2关节温度", 40, 80, "°C", 65),
            ("本体振动", 0.5, 3.0, "mm/s", 1.5),
            ("关节电流", 2, 12, "A", 8),
        ],
        "空压机": [
            ("排气温度", 70, 110, "°C", 95),
            ("排气压力", 0.5, 1.0, "MPa", 0.8),
            ("油温", 60, 95, "°C", 80),
            ("电机电流", 80, 160, "A", 135),
        ],
        "数控机床": [
            ("主轴温度", 35, 75, "°C", 60),
            ("主轴振动", 1.0, 5.0, "mm/s", 3.0),
            ("主轴电流", 10, 35, "A", 25),
            ("液压油温", 30, 60, "°C", 45),
        ],
    }

    config = sensor_configs.get(equipment_type, sensor_configs["通用旋转设备"])

    parts = [f"设备类型: {equipment_type}", f"采集时间: {now}", "传感器读数:"]
    parts.append(f"{'指标':<12} {'当前值':<10} {'正常范围':<15} {'告警阈值':<10} {'状态'}")
    parts.append("-" * 60)

    for name, min_val, max_val, unit, alarm_val in config:
        # 生成随机值（偏向正常范围）
        normal_max = alarm_val * 0.85
        value = round(random.uniform(min_val, normal_max), 1)
        # 10% 概率生成偏高值
        if random.random() < 0.1:
            value = round(random.uniform(normal_max, alarm_val * 1.1), 1)

        if value >= alarm_val:
            status = "🔴 报警"
        elif value >= alarm_val * 0.85:
            status = "🟡 注意"
        else:
            status = "🟢 正常"

        parts.append(f"{name:<12} {value}{unit:<6} [{min_val}~{max_val}]{unit:<4} {alarm_val}{unit:<6} {status}")

    return "\n".join(parts)
