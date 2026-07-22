"""工业智能制造领域工具：Function Calling 工具 + 节点直接调用函数。"""

import random  # 导入随机数模块，用于生成模拟传感器数据
import re  # 导入正则表达式模块，用于模式匹配和文本提取
from datetime import datetime  # 导入日期时间类，用于生成时间戳

from langchain_core.tools import tool  # 导入tool装饰器，用于将函数转为LangChain工具

from app.core.logging import setup_logger  # 导入日志初始化函数，用于创建模块专属日志器
from app.agents.manufacturing.knowledge import (  # 从工业知识模块导入查询和格式化函数
    format_equipment_spec,  # 设备参数格式化函数
    format_fault_code,  # 故障码格式化函数
    format_maintenance_rule,  # 维护规则格式化函数
    format_process_standard,  # 工艺标准格式化函数
    get_health_assessment_rules,  # 健康评估规则获取函数
    search_equipment_specs,  # 设备参数搜索函数
    search_fault_codes,  # 故障码搜索函数
    search_maintenance_rules,  # 维护规则搜索函数
    search_process_standards,  # 工艺标准搜索函数
)

logger = setup_logger("agents.manufacturing.tools")  # 创建工业工具模块的专属日志器


# ============================================================
# LangChain Function Calling 工具
# ============================================================

@tool  # 使用tool装饰器将函数转为LangChain工具
def query_fault_code(code: str) -> str:  # 故障码查询工具函数
    """查询工业设备故障码信息。输入故障码（如 E001）或关键词（如 过电流、振动），返回故障原因和维修方案。

    Args:
        code: 故障码或故障关键词
    """
    results = search_fault_codes(code)  # 调用知识库搜索故障码
    if not results:  # 如果没有搜索到结果
        return f"未找到与 '{code}' 相关的故障码信息。"  # 返回未找到提示
    formatted = [format_fault_code(r) for r in results[:3]]  # 取前3条结果并格式化
    return f"找到 {len(results)} 条相关故障信息：\n\n" + "\n\n---\n\n".join(formatted)  # 拼接并返回格式化结果


@tool  # 使用tool装饰器将函数转为LangChain工具
def query_equipment_params(model: str) -> str:  # 设备参数查询工具函数
    """查询工业设备的额定参数和告警阈值。输入设备型号（如 CNC-VMC850）或设备类型关键词。

    Args:
        model: 设备型号或类型关键词
    """
    results = search_equipment_specs(model)  # 调用知识库搜索设备参数
    if not results:  # 如果没有搜索到结果
        return f"未找到与 '{model}' 相关的设备参数信息。"  # 返回未找到提示
    formatted = [format_equipment_spec(r) for r in results[:3]]  # 取前3条结果并格式化
    return f"找到 {len(results)} 台相关设备：\n\n" + "\n\n---\n\n".join(formatted)  # 拼接并返回格式化结果


@tool  # 使用tool装饰器将函数转为LangChain工具
def simulate_sensor_data(equipment_type: str) -> str:  # 传感器数据模拟工具函数
    """模拟工业设备传感器实时读数。输入设备类型（如 电机、液压站、空压机），返回模拟的温度/振动/压力等数据及状态评估。

    Args:
        equipment_type: 设备类型名称
    """
    return _generate_sensor_data(equipment_type)  # 调用内部函数生成传感器数据


@tool  # 使用tool装饰器将函数转为LangChain工具
def check_maintenance_schedule(equipment_type: str, running_hours: int = 1000) -> str:  # 维护计划查询工具函数
    """查询设备维护计划和保养建议。输入设备类型和已运行小时数，返回应执行的维护项目。

    Args:
        equipment_type: 设备类型（如 旋转设备、液压系统、工业机器人、空压机）
        running_hours: 设备已运行小时数
    """
    rules = search_maintenance_rules(equipment_type)  # 搜索指定设备类型的维护规则
    if not rules:  # 如果没有找到规则
        rules = search_maintenance_rules("")  # 返回所有规则
    if not rules:  # 如果仍然没有规则
        return "未找到相关维护规则。"  # 返回未找到提示

    parts = [f"设备类型: {equipment_type}，已运行: {running_hours} 小时\n"]  # 初始化输出部分，包含设备类型和运行时长
    parts.append("维护计划建议：\n")  # 添加维护计划标题

    for rule in rules[:4]:  # 遍历前4条维护规则
        interval = rule.get("interval_hours", 0)  # 获取维护周期小时数
        level = rule.get("level", "")  # 获取维护级别
        # 判断是否到期
        if interval > 0 and running_hours >= interval:  # 如果已运行时长超过周期
            status = "⚠️ 已到期" if running_hours >= interval * 1.2 else "📋 即将到期"  # 判断是已到期还是即将到期
        else:  # 如果未到期
            remaining = interval - running_hours if interval > 0 else "N/A"  # 计算剩余小时数
            status = f"✅ 剩余 {remaining}h"  # 显示剩余时间
        parts.append(f"- [{level}] 周期 {interval}h | 状态: {status}")  # 添加规则状态行
        parts.append(f"  项目: {', '.join(rule.get('items', [])[:3])}...")  # 添加维护项目（前3项）

    parts.append(f"\n{get_health_assessment_rules()}")  # 添加健康评估规则
    return "\n".join(parts)  # 拼接并返回所有部分


@tool  # 使用tool装饰器将函数转为LangChain工具
def analyze_process_params(process_name: str) -> str:  # 工艺参数分析工具函数
    """查询工业生产工艺参数标准。输入工艺名称（如 注塑、CNC铣削、焊接、SMT），返回标准参数范围和常见缺陷对策。

    Args:
        process_name: 工艺名称关键词
    """
    results = search_process_standards(process_name)  # 搜索工艺标准
    if not results:  # 如果没有搜索到结果
        return f"未找到与 '{process_name}' 相关的工艺标准。"  # 返回未找到提示
    formatted = [format_process_standard(r) for r in results[:2]]  # 取前2条结果并格式化
    return f"找到 {len(results)} 种相关工艺：\n\n" + "\n\n---\n\n".join(formatted)  # 拼接并返回格式化结果


# 工业工具列表（供 bind_tools 使用）
MFG_TOOLS = [  # 工业工具列表，供LLM绑定工具使用
    query_fault_code,  # 故障码查询工具
    query_equipment_params,  # 设备参数查询工具
    simulate_sensor_data,  # 传感器数据模拟工具
    check_maintenance_schedule,  # 维护计划查询工具
    analyze_process_params,  # 工艺参数分析工具
]


# ============================================================
# 节点直接调用函数（非 LangChain tool，供 nodes.py 使用）
# ============================================================

def query_fault_code_by_text(text: str) -> str:  # 从用户问题文本中提取故障码并查询
    """从用户问题文本中提取故障码并查询。"""
    # 尝试提取故障码模式（E001, e001, E-001 等）
    code_pattern = re.compile(r'[Ee][-_]?(\d{3,4})')  # 编译故障码正则模式
    match = code_pattern.search(text)  # 在文本中搜索故障码
    if match:  # 如果匹配到故障码
        code = f"E{match.group(1)}"  # 构建标准故障码格式
        results = search_fault_codes(code)  # 搜索故障码信息
        if results:  # 如果搜索到结果
            return "\n\n".join(format_fault_code(r) for r in results[:2])  # 格式化并返回前2条结果

    # 无明确故障码时，用关键词搜索
    keywords = _extract_keywords(text)  # 从文本中提取故障关键词
    if keywords:  # 如果提取到关键词
        results = search_fault_codes(keywords)  # 用关键词搜索故障码
        if results:  # 如果搜索到结果
            return "\n\n".join(format_fault_code(r) for r in results[:2])  # 格式化并返回前2条结果

    return ""  # 返回空字符串


def simulate_sensor_by_text(text: str) -> str:  # 根据用户问题生成模拟传感器数据
    """根据用户问题中的设备类型生成模拟传感器数据。"""
    equipment_type = _detect_equipment_type(text)  # 从文本中检测设备类型
    return _generate_sensor_data(equipment_type)  # 生成并返回传感器数据


def check_maintenance_by_text(text: str) -> str:  # 根据用户问题查询维护计划
    """根据用户问题提取设备类型和运行时长，查询维护计划。"""
    equipment_type = _detect_equipment_type(text)  # 从文本中检测设备类型
    # 尝试提取运行时长
    hours_match = re.search(r'(\d+)\s*(?:小时|h|hour)', text, re.IGNORECASE)  # 正则匹配运行时长
    running_hours = int(hours_match.group(1)) if hours_match else 1000  # 提取运行时长，默认1000小时

    rules = search_maintenance_rules(equipment_type)  # 搜索维护规则
    if not rules:  # 如果没有找到规则
        return ""  # 返回空字符串

    parts = []  # 初始化输出部分列表
    for rule in rules[:3]:  # 遍历前3条规则
        parts.append(format_maintenance_rule(rule))  # 格式化规则并添加到列表
    return "\n\n---\n\n".join(parts)  # 用分隔符拼接并返回


def analyze_process_params_by_text(text: str) -> str:  # 根据用户问题查询工艺标准
    """根据用户问题中的工艺关键词查询工艺标准。"""
    process_keywords = ["注塑", "CNC", "铣削", "焊接", "SMT", "贴片", "切削", "成型"]  # 工艺关键词列表
    for kw in process_keywords:  # 遍历工艺关键词
        if kw in text:  # 如果文本包含该关键词
            results = search_process_standards(kw)  # 搜索对应工艺标准
            if results:  # 如果搜索到结果
                return "\n\n".join(format_process_standard(r) for r in results[:2])  # 格式化并返回前2条结果
    return ""  # 返回空字符串


# 供路由层 REST 接口使用
def search_fault_codes_api(keyword: str) -> list[dict]:  # 故障码搜索API函数
    """故障码搜索（REST API 用）。"""
    return search_fault_codes(keyword)  # 调用知识库搜索并返回原始结果列表


def search_equipment_specs_api(keyword: str) -> list[dict]:  # 设备参数搜索API函数
    """设备参数搜索（REST API 用）。"""
    return search_equipment_specs(keyword)  # 调用知识库搜索并返回原始结果列表


# ============================================================
# 辅助函数
# ============================================================

def _extract_keywords(text: str) -> str:  # 从文本中提取故障相关关键词
    """从文本中提取故障相关关键词。"""
    fault_keywords = [  # 故障关键词列表
        "过电流", "过电压", "过热", "振动", "泄漏", "压力不足",  # 电气和机械故障关键词
        "通信中断", "伺服", "报警", "停机", "异响", "漏油",  # 控制和润滑故障关键词
        "温度高", "油温", "冷却", "润滑", "接地", "跳闸",  # 温度和安全故障关键词
    ]
    found = [kw for kw in fault_keywords if kw in text]  # 找出文本中包含的关键词
    return found[0] if found else ""  # 返回第一个匹配的关键词，无匹配则返回空


def _detect_equipment_type(text: str) -> str:  # 从文本中检测设备类型
    """从文本中检测设备类型。"""
    type_map = {  # 设备关键词到标准设备类型的映射表
        "机器人": "工业机器人",  # 机器人映射
        "机械臂": "工业机器人",  # 机械臂映射
        "液压": "液压系统",  # 液压映射
        "空压机": "空压机",  # 空压机映射
        "压缩机": "空压机",  # 压缩机映射
        "水泵": "离心水泵",  # 水泵映射
        "电机": "通用旋转设备",  # 电机映射
        "CNC": "数控机床",  # CNC映射
        "加工中心": "数控机床",  # 加工中心映射
        "注塑机": "注塑设备",  # 注塑机映射
    }
    for keyword, eq_type in type_map.items():  # 遍历映射表
        if keyword in text:  # 如果文本包含关键词
            return eq_type  # 返回对应设备类型
    return "通用旋转设备"  # 默认返回通用旋转设备


def _generate_sensor_data(equipment_type: str) -> str:  # 生成模拟传感器数据
    """生成模拟传感器数据。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 获取当前时间并格式化

    # 根据设备类型生成不同的传感器数据
    sensor_configs = {  # 设备类型到传感器配置的映射表
        "通用旋转设备": [  # 通用旋转设备传感器配置
            ("轴承温度", 55, 85, "°C", 75),  # 指标名、最小值、最大值、单位、告警阈值
            ("振动值", 1.5, 7.0, "mm/s", 4.5),  # 振动值配置
            ("电机电流", 15, 60, "A", 50),  # 电机电流配置
            ("转速", 1400, 3000, "rpm", 2950),  # 转速配置
        ],
        "液压系统": [  # 液压系统传感器配置
            ("油温", 35, 70, "°C", 55),  # 油温配置
            ("系统压力", 5, 25, "MPa", 16),  # 系统压力配置
            ("油液清洁度", 6, 12, "NAS", 8),  # 油液清洁度配置
            ("泵出口流量", 20, 100, "L/min", 63),  # 泵出口流量配置
        ],
        "工业机器人": [  # 工业机器人传感器配置
            ("J1关节温度", 40, 80, "°C", 65),  # J1关节温度配置
            ("J2关节温度", 40, 80, "°C", 65),  # J2关节温度配置
            ("本体振动", 0.5, 3.0, "mm/s", 1.5),  # 本体振动配置
            ("关节电流", 2, 12, "A", 8),  # 关节电流配置
        ],
        "空压机": [  # 空压机传感器配置
            ("排气温度", 70, 110, "°C", 95),  # 排气温度配置
            ("排气压力", 0.5, 1.0, "MPa", 0.8),  # 排气压力配置
            ("油温", 60, 95, "°C", 80),  # 油温配置
            ("电机电流", 80, 160, "A", 135),  # 电机电流配置
        ],
        "数控机床": [  # 数控机床传感器配置
            ("主轴温度", 35, 75, "°C", 60),  # 主轴温度配置
            ("主轴振动", 1.0, 5.0, "mm/s", 3.0),  # 主轴振动配置
            ("主轴电流", 10, 35, "A", 25),  # 主轴电流配置
            ("液压油温", 30, 60, "°C", 45),  # 液压油温配置
        ],
    }

    config = sensor_configs.get(equipment_type, sensor_configs["通用旋转设备"])  # 获取设备配置，默认为通用旋转设备

    parts = [f"设备类型: {equipment_type}", f"采集时间: {now}", "传感器读数:"]  # 初始化输出部分，包含设备类型、时间、标题
    parts.append(f"{'指标':<12} {'当前值':<10} {'正常范围':<15} {'告警阈值':<10} {'状态'}")  # 添加表头
    parts.append("-" * 60)  # 添加分隔线

    for name, min_val, max_val, unit, alarm_val in config:  # 遍历传感器配置
        # 生成随机值（偏向正常范围）
        normal_max = alarm_val * 0.85  # 计算正常范围上限
        value = round(random.uniform(min_val, normal_max), 1)  # 生成正常范围内的随机值
        # 10% 概率生成偏高值
        if random.random() < 0.1:  # 10%概率生成异常值
            value = round(random.uniform(normal_max, alarm_val * 1.1), 1)  # 生成偏高值

        if value >= alarm_val:  # 如果超过告警阈值
            status = "🔴 报警"  # 状态为报警
        elif value >= alarm_val * 0.85:  # 如果超过注意阈值
            status = "🟡 注意"  # 状态为注意
        else:  # 否则
            status = "🟢 正常"  # 状态为正常

        parts.append(f"{name:<12} {value}{unit:<6} [{min_val}~{max_val}]{unit:<4} {alarm_val}{unit:<6} {status}")  # 添加数据行

    return "\n".join(parts)  # 拼接并返回所有部分
