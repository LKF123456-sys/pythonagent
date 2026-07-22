"""工业制造领域预置知识加载与格式化。

从 data/manufacturing/*.json 加载故障码、设备参数、工艺标准、维护规则，
并提供格式化为 LLM 可消费文本的工具函数。
"""

import json  # 导入JSON模块，用于解析JSON数据文件
import os  # 导入操作系统模块，用于路径操作
from functools import lru_cache  # 导入LRU缓存装饰器，用于缓存函数结果避免重复加载
from typing import Optional  # 导入Optional类型，用于可选类型注解

from app.core.logging import setup_logger  # 导入日志初始化函数，用于创建模块专属日志器

logger = setup_logger("agents.manufacturing.knowledge")  # 创建工业知识模块的专属日志器

# 数据目录（相对于项目根）
_DATA_DIR = os.path.join(  # 构建工业数据目录路径
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),  # 向上回溯4级目录到项目根
    "data", "manufacturing"  # 拼接data和manufacturing子目录
)


@lru_cache(maxsize=1)  # 使用LRU缓存，最大缓存1次，避免重复加载
def _load_fault_codes() -> list[dict]:  # 加载故障码知识库函数
    """加载故障码知识库。"""
    path = os.path.join(_DATA_DIR, "fault_codes.json")  # 构建故障码JSON文件路径
    try:  # 尝试加载文件
        with open(path, "r", encoding="utf-8") as f:  # 以UTF-8编码打开文件
            data = json.load(f)  # 解析JSON数据
        codes = data.get("fault_codes", [])  # 获取故障码列表，默认为空
        logger.info("故障码知识库加载成功: %d 条", len(codes))  # 记录加载成功日志
        return codes  # 返回故障码列表
    except Exception as e:  # 捕获异常
        logger.warning("故障码知识库加载失败: %s", e)  # 记录警告日志
        return []  # 返回空列表


@lru_cache(maxsize=1)  # 使用LRU缓存，最大缓存1次，避免重复加载
def _load_equipment_specs() -> list[dict]:  # 加载设备参数规格库函数
    """加载设备参数规格库。"""
    path = os.path.join(_DATA_DIR, "equipment_specs.json")  # 构建设备参数JSON文件路径
    try:  # 尝试加载文件
        with open(path, "r", encoding="utf-8") as f:  # 以UTF-8编码打开文件
            data = json.load(f)  # 解析JSON数据
        specs = data.get("equipment", [])  # 获取设备列表，默认为空
        logger.info("设备参数库加载成功: %d 台设备", len(specs))  # 记录加载成功日志
        return specs  # 返回设备规格列表
    except Exception as e:  # 捕获异常
        logger.warning("设备参数库加载失败: %s", e)  # 记录警告日志
        return []  # 返回空列表


@lru_cache(maxsize=1)  # 使用LRU缓存，最大缓存1次，避免重复加载
def _load_process_standards() -> list[dict]:  # 加载工艺参数标准库函数
    """加载工艺参数标准库。"""
    path = os.path.join(_DATA_DIR, "process_standards.json")  # 构建工艺标准JSON文件路径
    try:  # 尝试加载文件
        with open(path, "r", encoding="utf-8") as f:  # 以UTF-8编码打开文件
            data = json.load(f)  # 解析JSON数据
        processes = data.get("processes", [])  # 获取工艺列表，默认为空
        logger.info("工艺标准库加载成功: %d 种工艺", len(processes))  # 记录加载成功日志
        return processes  # 返回工艺标准列表
    except Exception as e:  # 捕获异常
        logger.warning("工艺标准库加载失败: %s", e)  # 记录警告日志
        return []  # 返回空列表


@lru_cache(maxsize=1)  # 使用LRU缓存，最大缓存1次，避免重复加载
def _load_maintenance_rules() -> list[dict]:  # 加载维护规则库函数
    """加载维护规则库。"""
    path = os.path.join(_DATA_DIR, "maintenance_rules.json")  # 构建维护规则JSON文件路径
    try:  # 尝试加载文件
        with open(path, "r", encoding="utf-8") as f:  # 以UTF-8编码打开文件
            data = json.load(f)  # 解析JSON数据
        rules = data.get("maintenance_rules", [])  # 获取维护规则列表，默认为空
        logger.info("维护规则库加载成功: %d 条规则", len(rules))  # 记录加载成功日志
        return rules  # 返回维护规则列表
    except Exception as e:  # 捕获异常
        logger.warning("维护规则库加载失败: %s", e)  # 记录警告日志
        return []  # 返回空列表


@lru_cache(maxsize=1)  # 使用LRU缓存，最大缓存1次，避免重复加载
def _load_health_rules() -> dict:  # 加载健康评估规则函数
    """加载健康评估规则。"""
    path = os.path.join(_DATA_DIR, "maintenance_rules.json")  # 构建维护规则JSON文件路径（健康规则在同一文件）
    try:  # 尝试加载文件
        with open(path, "r", encoding="utf-8") as f:  # 以UTF-8编码打开文件
            data = json.load(f)  # 解析JSON数据
        return data.get("health_assessment_rules", {})  # 获取健康评估规则，默认为空字典
    except Exception:  # 捕获异常
        return {}  # 返回空字典


# ============================================================
# 查询接口
# ============================================================

def search_fault_codes(keyword: str = "") -> list[dict]:  # 故障码搜索函数
    """根据关键词搜索故障码（支持故障码/名称/类别/症状模糊匹配）。"""
    codes = _load_fault_codes()  # 加载故障码知识库
    if not keyword:  # 如果没有关键词
        return codes  # 返回所有故障码
    keyword_lower = keyword.lower()  # 将关键词转为小写用于不区分大小写匹配
    results = []  # 初始化结果列表
    for item in codes:  # 遍历所有故障码
        searchable = f"{item.get('code', '')} {item.get('name', '')} {item.get('category', '')} {item.get('symptom', '')}".lower()  # 拼接可搜索字段并小写化
        if keyword_lower in searchable:  # 如果关键词在可搜索字段中
            results.append(item)  # 添加到结果列表
    return results  # 返回匹配结果


def search_equipment_specs(keyword: str = "") -> list[dict]:  # 设备参数搜索函数
    """根据关键词搜索设备参数。"""
    specs = _load_equipment_specs()  # 加载设备参数规格库
    if not keyword:  # 如果没有关键词
        return specs  # 返回所有设备参数
    keyword_lower = keyword.lower()  # 将关键词转为小写
    results = []  # 初始化结果列表
    for item in specs:  # 遍历所有设备参数
        searchable = f"{item.get('model', '')} {item.get('name', '')} {item.get('category', '')}".lower()  # 拼接可搜索字段并小写化
        if keyword_lower in searchable:  # 如果关键词在可搜索字段中
            results.append(item)  # 添加到结果列表
    return results  # 返回匹配结果


def search_process_standards(keyword: str = "") -> list[dict]:  # 工艺标准搜索函数
    """根据关键词搜索工艺标准。"""
    processes = _load_process_standards()  # 加载工艺参数标准库
    if not keyword:  # 如果没有关键词
        return processes  # 返回所有工艺标准
    keyword_lower = keyword.lower()  # 将关键词转为小写
    results = []  # 初始化结果列表
    for item in processes:  # 遍历所有工艺标准
        searchable = f"{item.get('process_id', '')} {item.get('name', '')} {item.get('category', '')}".lower()  # 拼接可搜索字段并小写化
        if keyword_lower in searchable:  # 如果关键词在可搜索字段中
            results.append(item)  # 添加到结果列表
    return results  # 返回匹配结果


def search_maintenance_rules(keyword: str = "") -> list[dict]:  # 维护规则搜索函数
    """根据关键词搜索维护规则。"""
    rules = _load_maintenance_rules()  # 加载维护规则库
    if not keyword:  # 如果没有关键词
        return rules  # 返回所有维护规则
    keyword_lower = keyword.lower()  # 将关键词转为小写
    results = []  # 初始化结果列表
    for item in rules:  # 遍历所有维护规则
        searchable = f"{item.get('rule_id', '')} {item.get('equipment_type', '')} {item.get('level', '')}".lower()  # 拼接可搜索字段并小写化
        if keyword_lower in searchable:  # 如果关键词在可搜索字段中
            results.append(item)  # 添加到结果列表
    return results  # 返回匹配结果


# ============================================================
# 格式化为 LLM 可消费文本
# ============================================================

def format_fault_code(fault: dict) -> str:  # 故障码格式化函数
    """将单条故障码格式化为文本。"""
    parts = [  # 构建格式化文本部分列表
        f"故障码: {fault.get('code', 'N/A')}",  # 故障码
        f"名称: {fault.get('name', 'N/A')}",  # 故障名称
        f"类别: {fault.get('category', 'N/A')}",  # 故障类别
        f"适用设备: {fault.get('equipment', '通用')}",  # 适用设备
        f"故障现象: {fault.get('symptom', '')}",  # 故障现象
        f"可能原因: {', '.join(fault.get('causes', []))}",  # 可能原因列表
        f"维修步骤: {' → '.join(fault.get('repair_steps', []))}",  # 维修步骤
        f"所需备件: {', '.join(fault.get('parts', []))}",  # 所需备件
        f"严重程度: {fault.get('severity', 'medium')}",  # 严重程度
        f"安全提示: {fault.get('safety_note', '')}",  # 安全提示
    ]
    return "\n".join(parts)  # 用换行符拼接并返回


def format_equipment_spec(spec: dict) -> str:  # 设备参数格式化函数
    """将设备参数格式化为文本。"""
    parts = [  # 构建格式化文本部分列表
        f"设备型号: {spec.get('model', 'N/A')}",  # 设备型号
        f"设备名称: {spec.get('name', 'N/A')}",  # 设备名称
        f"类别: {spec.get('category', 'N/A')}",  # 设备类别
        "额定参数:",  # 额定参数标题
    ]
    for name, param in spec.get("rated_params", {}).items():  # 遍历额定参数
        parts.append(f"  - {name}: {param.get('value')}{param.get('unit', '')} (最大: {param.get('max')}{param.get('unit', '')})")  # 添加参数详情
    parts.append("告警阈值:")  # 添加告警阈值标题
    for name, threshold in spec.get("alarm_thresholds", {}).items():  # 遍历告警阈值
        parts.append(f"  - {name}: 预警 {threshold.get('warning')}{threshold.get('unit', '')} / 报警 {threshold.get('alarm')}{threshold.get('unit', '')}")  # 添加阈值详情
    cycle = spec.get("maintenance_cycle", {})  # 获取维护周期
    if cycle:  # 如果有维护周期
        parts.append(f"维护周期: 日常 {cycle.get('日常保养', 'N/A')}h / 一级 {cycle.get('一级保养', 'N/A')}h / 二级 {cycle.get('二级保养', 'N/A')}h")  # 添加维护周期详情
    return "\n".join(parts)  # 用换行符拼接并返回


def format_process_standard(process: dict) -> str:  # 工艺标准格式化函数
    """将工艺标准格式化为文本。"""
    parts = [  # 构建格式化文本部分列表
        f"工艺名称: {process.get('name', 'N/A')}",  # 工艺名称
        f"类别: {process.get('category', 'N/A')}",  # 工艺类别
        "标准参数:",  # 标准参数标题
    ]
    for name, param in process.get("parameters", {}).items():  # 遍历工艺参数
        parts.append(  # 添加参数详情
            f"  - {name}: 范围 [{param.get('min')}~{param.get('max')}] 最优 {param.get('optimal')} {param.get('unit', '')} ({param.get('note', '')})"
        )
    defects = process.get("common_defects", {})  # 获取常见缺陷
    if defects:  # 如果有常见缺陷
        parts.append("常见缺陷:")  # 添加常见缺陷标题
        for name, info in defects.items():  # 遍历常见缺陷
            parts.append(f"  - {name}: 原因={info.get('cause', '')} | 对策={info.get('solution', '')}")  # 添加缺陷详情
    return "\n".join(parts)  # 用换行符拼接并返回


def format_maintenance_rule(rule: dict) -> str:  # 维护规则格式化函数
    """将维护规则格式化为文本。"""
    parts = [  # 构建格式化文本部分列表
        f"维护级别: {rule.get('level', 'N/A')}",  # 维护级别
        f"适用设备: {rule.get('equipment_type', '通用')}",  # 适用设备类型
        f"周期: 每 {rule.get('interval_hours', 'N/A')} 小时",  # 维护周期
        f"预计耗时: {rule.get('estimated_time_min', 'N/A')} 分钟",  # 预计耗时
        "保养项目:",  # 保养项目标题
    ]
    for i, item in enumerate(rule.get("items", []), 1):  # 遍历保养项目，从1开始编号
        parts.append(f"  {i}. {item}")  # 添加编号项目
    tools = rule.get("tools", [])  # 获取所需工具
    if tools:  # 如果有工具
        parts.append(f"所需工具: {', '.join(tools)}")  # 添加工具列表
    return "\n".join(parts)  # 用换行符拼接并返回


def get_health_assessment_rules() -> str:  # 获取健康评估规则文本函数
    """获取健康评估规则文本。"""
    rules = _load_health_rules()  # 加载健康评估规则
    if not rules:  # 如果没有规则
        return ""  # 返回空字符串
    parts = ["设备健康度评估标准:"]  # 初始化输出部分，添加标题
    scoring = rules.get("scoring", {})  # 获取评分规则
    for level, info in scoring.items():  # 遍历评分等级
        r = info.get("range", [0, 0])  # 获取分数范围
        parts.append(f"  - {info.get('label', level)} ({r[0]}-{r[1]}分): {info.get('action', '')}")  # 添加等级详情
    factors = rules.get("degradation_factors", [])  # 获取退化权重因子
    if factors:  # 如果有退化因子
        parts.append("退化权重因子:")  # 添加退化因子标题
        for f in factors:  # 遍历退化因子
            parts.append(f"  - {f.get('factor', '')}: {f.get('weight', 0)*100:.0f}%")  # 添加因子详情
    return "\n".join(parts)  # 用换行符拼接并返回
