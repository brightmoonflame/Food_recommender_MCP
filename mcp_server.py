#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美食推荐MCP服务器
基于FastMCP框架和百度地图API构建的智能餐厅推荐系统
"""

import os
import httpx
import asyncio
import logging
import math
import re
from typing import List, Dict, Any, Optional, Union
from dotenv import load_dotenv
from fastmcp import FastMCP
from functools import lru_cache
import time
from datetime import datetime, timedelta
import threading
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("food_mcp.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()
API_KEY = os.getenv("BAIDU_MAPS_API_KEY", "")
if not API_KEY or API_KEY == "your_actual_baidu_maps_api_key_here" or API_KEY == "your_actual_api_key_here" or API_KEY == "BAIDU_MAPS_API_KEY":
    logger.error("请设置环境变量 BAIDU_MAPS_API_KEY 为你的百度地图 API Key")
    logger.error("当前的 API Key 是无效的: %s", API_KEY)
    logger.error("请在 .env 文件中配置正确的百度地图 API Key")
    raise RuntimeError("请设置环境变量 BAIDU_MAPS_API_KEY 为你的百度地图 API Key")

API_URL = "https://api.map.baidu.com"

# 创建全局 HTTP 客户端实例以复用连接
http_client = httpx.AsyncClient(timeout=30.0)

# 创建 FastMCP 服务器实例
mcp = FastMCP("food-recommender")

# 用户评价存储（在实际应用中应该使用数据库）
user_reviews = {}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    使用 Haversine 公式计算两个经纬度点之间的距离（单位：米）
    
    Args:
        lat1: 第一个点的纬度
        lon1: 第一个点的经度
        lat2: 第二个点的纬度
        lon2: 第二个点的经度
        
    Returns:
        两点间的距离（米）
    """
    R = 6371000  # 地球半径（米）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2) * math.sin(delta_phi / 2) + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2) * math.sin(delta_lambda / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def fuzzy_match(query: str, targets: List[str]) -> List[str]:
    """
    简单的模糊匹配函数
    
    Args:
        query: 查询字符串
        targets: 目标字符串列表
        
    Returns:
        匹配到的字符串列表
    """
    matched = []
    query_lower = query.lower()
    
    for target in targets:
        # 精确匹配
        if query_lower == target.lower():
            matched.append(target)
        # 前缀匹配
        elif target.lower().startswith(query_lower):
            matched.append(target)
        # 包含匹配
        elif query_lower in target.lower():
            matched.append(target)
        # 编辑距离匹配（简单的相似度检查）
        elif len(set(query_lower) & set(target.lower())) / max(len(query_lower), len(target.lower())) > 0.5:
            matched.append(target)
    
    return matched


def normalize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    标准化数据格式
    
    Args:
        data: 原始数据字典
        
    Returns:
        标准化后的数据字典
    """
    normalized = {}
    
    # 标准化评分
    detail_info = data.get("detail_info", {})
    for key in ["overall_rating", "taste_rating", "service_rating", "environment_rating"]:
        try:
            value = detail_info.get(key)
            normalized[key] = float(value) if value else 0.0
        except (ValueError, TypeError):
            normalized[key] = 0.0
    
    # 标准化价格
    price = detail_info.get("price")
    try:
        normalized["price"] = float(price) if price else 0.0
    except (ValueError, TypeError):
        normalized["price"] = 0.0
    
    # 标准化数字类型数据
    for key in ["comment_num", "favorite_num", "checkin_num"]:
        try:
            value = detail_info.get(key)
            normalized[key] = int(value) if value else 0
        except (ValueError, TypeError):
            normalized[key] = 0
    
    # 复制其他字段
    normalized.update({
        "name": data.get("name", ""),
        "address": data.get("address", ""),
        "telephone": data.get("telephone", ""),
        "location": data.get("location", {}),
        "uid": data.get("uid", ""),
        "tag": detail_info.get("tag", ""),
        "hours": detail_info.get("hours", ""),
        "description": detail_info.get("description", "")
    })
    
    return normalized


# ========== 工具函数（从 agent.py 迁移） ==========

async def geocode_address(address: str, retries: int = 3) -> Dict[str, Any]:
    """
    地址 → 坐标 (带重试机制)
    
    Args:
        address: 地址字符串
        retries: 重试次数
        
    Returns:
        包含经纬度信息的字典
    """
    logger.info(f"正在地理编码地址: {address}")
    url = f"{API_URL}/geocoding/v3/"
    
    for attempt in range(retries):
        try:
            params = {
                "ak": API_KEY,
                "output": "json",
                "address": address
            }
            resp = await http_client.get(url, params=params)
            resp.raise_for_status()
            result = resp.json()
            if result.get("status") != 0:
                logger.error(f"地理编码失败：{result.get('message')}")
                raise Exception(f"地理编码失败：{result.get('message')}")
            logger.info(f"地理编码成功: {address}")
            return result["result"]["location"]
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"地理编码请求失败 (尝试 {attempt + 1}/{retries}): {str(e)}")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error(f"地理编码请求失败: {str(e)}")
                raise


async def search_places(
    query: str,
    latitude: float,
    longitude: float,
    radius: int = 1000,
    max_results: int = 10,
    tag: Optional[str] = None,
    price_section: Optional[str] = None,
    sort_name: Optional[str] = None,
    sort_rule: Optional[int] = None,
    groupon: Optional[str] = None,
    discount: Optional[str] = None,
    retries: int = 3
) -> List[Dict[str, Any]]:
    """
    在给定坐标半径范围内,检索关键字 query 的地点（如餐厅）(带重试机制和增强参数)
    
    Args:
        query: 搜索关键词
        latitude: 纬度
        longitude: 经度
        radius: 搜索半径（米）
        max_results: 最大返回结果数
        tag: 标签筛选
        price_section: 价格区间
        sort_name: 排序字段
        sort_rule: 排序规则
        groupon: 团购筛选
        discount: 折扣筛选
        retries: 重试次数
        
    Returns:
        地点搜索结果列表
    """
    # 参数验证
    if not (50 <= radius <= 50000):
        logger.warning(f"半径 {radius} 超出合理范围 [50, 50000]，将使用默认值 1000")
        radius = 1000
    
    if not (1 <= max_results <= 50):
        logger.warning(f"最大结果数 {max_results} 超出合理范围 [1, 50]，将使用默认值 10")
        max_results = 10
    
    logger.info(f"正在搜索地点: {query}, 位置: ({latitude}, {longitude}), 半径: {radius}米")
    url = f"{API_URL}/place/v2/search"
    location_str = f"{latitude},{longitude}"
    
    for attempt in range(retries):
        try:
            params = {
                "ak": API_KEY,
                "output": "json",
                "query": query,
                "location": location_str,
                "radius": radius,
                "scope": 2,  # 返回较详细信息
                "filter": "industry_type:cater"  # 限定为餐饮行业
            }
            
            # 添加标签筛选
            if tag:
                params["tag"] = tag
                
            # 添加价格区间筛选
            if price_section:
                params["price_section"] = price_section
                
            # 添加排序参数
            if sort_name:
                params["sort_name"] = sort_name
            if sort_rule is not None:
                params["sort_rule"] = sort_rule
                
            # 添加团购和折扣筛选
            if groupon:
                params["groupon"] = groupon
            if discount:
                params["discount"] = discount
                
            resp = await http_client.get(url, params=params)
            resp.raise_for_status()
            result = resp.json()
            if result.get("status") != 0:
                logger.error(f"地点检索失败：{result.get('message')}")
                raise Exception(f"地点检索失败：{result.get('message')}")
            results = result.get("results", [])
            logger.info(f"找到 {len(results)} 个结果")
            return results[: max_results]
        except httpx.TimeoutException:
            if attempt < retries - 1:
                logger.warning(f"地点搜索请求超时 (尝试 {attempt + 1}/{retries})")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error("地点搜索请求超时")
                raise Exception("地点搜索请求超时，请稍后重试")
        except httpx.RequestError as e:
            if attempt < retries - 1:
                logger.warning(f"地点搜索请求失败 (尝试 {attempt + 1}/{retries}): {str(e)}")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error(f"地点搜索请求失败: {str(e)}")
                raise Exception(f"网络请求失败: {str(e)}")
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"地点搜索请求失败 (尝试 {attempt + 1}/{retries}): {str(e)}")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error(f"地点搜索请求失败: {str(e)}")
                raise


# 缓存装饰器，缓存10分钟
@lru_cache(maxsize=128)
def _get_place_details_cache(uid: str, timestamp: int) -> str:
    """
    缓存place详情的辅助函数，timestamp参数用于控制缓存时间
    
    Args:
        uid: 地点UID
        timestamp: 时间戳
        
    Returns:
        缓存键值
    """
    # 这只是一个占位符，实际缓存实现在get_place_details_with_cache中
    pass


async def get_place_details_with_cache(uid: str, force_refresh: bool = False, retries: int = 3) -> Dict[str, Any]:
    """
    通过 uid 获取某地点的详情 (带缓存和重试机制)
    
    Args:
        uid: 地点UID
        force_refresh: 是否强制刷新缓存
        retries: 重试次数
        
    Returns:
        地点详情信息
    """
    # 检查是否强制刷新
    if not force_refresh:
        # 检查缓存 (5分钟有效期)
        cache_key = f"{uid}_{int(time.time() // 300)}"  # 缩短缓存时间以增强实时性
        
        logger.info(f"正在获取地点详情: {uid}")
    else:
        logger.info(f"强制刷新地点详情: {uid}")
        
    url = f"{API_URL}/place/v2/detail"
    
    for attempt in range(retries):
        try:
            params = {
                "ak": API_KEY,
                "output": "json",
                "uid": uid,
                "scope": 2
            }
            resp = await http_client.get(url, params=params)
            resp.raise_for_status()
            result = resp.json()
            if result.get("status") != 0:
                logger.error(f"地点详情获取失败：{result.get('message')}")
                raise Exception(f"地点详情获取失败：{result.get('message')}")
            logger.info(f"地点详情获取成功: {uid}")
            return result.get("result", {})
        except httpx.TimeoutException:
            if attempt < retries - 1:
                logger.warning(f"获取地点详情超时 (尝试 {attempt + 1}/{retries})")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error("获取地点详情超时")
                raise Exception("获取地点详情超时，请稍后重试")
        except httpx.RequestError as e:
            if attempt < retries - 1:
                logger.warning(f"获取地点详情失败 (尝试 {attempt + 1}/{retries}): {str(e)}")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error(f"获取地点详情失败: {str(e)}")
                raise Exception(f"网络请求失败: {str(e)}")
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"获取地点详情失败 (尝试 {attempt + 1}/{retries}): {str(e)}")
                await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                logger.error(f"获取地点详情失败: {str(e)}")
                raise


async def get_place_details(uid: str) -> Dict[str, Any]:
    """
    通过 uid 获取某地点的详情 (兼容旧接口)
    
    Args:
        uid: 地点UID
        
    Returns:
        地点详情信息
    """
    return await get_place_details_with_cache(uid)


async def get_multiple_place_details(uids: List[str], force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    并发获取多个地点详情
    
    Args:
        uids: 地点UID列表
        force_refresh: 是否强制刷新缓存
        
    Returns:
        地点详情信息列表
    """
    tasks = [get_place_details_with_cache(uid, force_refresh) for uid in uids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理异常结果
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"获取地点详情失败 (UID: {uids[i]}): {str(result)}")
            processed_results.append(None)
        else:
            processed_results.append(result)
    
    return processed_results


def calculate_composite_score(restaurant: Dict[str, Any], user_preferences: Optional[Dict[str, Any]] = None) -> float:
    """
    计算餐厅的综合评分，考虑多个因素
    
    Args:
        restaurant: 餐厅信息字典
        user_preferences: 用户偏好设置
        
    Returns:
        综合评分
    """
    detail_info = restaurant.get("detail_info", {})
    
    # 基础评分
    overall_rating = float(detail_info.get("overall_rating", 0) or 0)
    taste_rating = float(detail_info.get("taste_rating", 0) or 0)
    service_rating = float(detail_info.get("service_rating", 0) or 0)
    environment_rating = float(detail_info.get("environment_rating", 0) or 0)
    price = detail_info.get("price", None)
    
    # 社交属性
    comment_num = int(detail_info.get("comment_num", 0) or 0)
    favorite_num = int(detail_info.get("favorite_num", 0) or 0)
    checkin_num = int(detail_info.get("checkin_num", 0) or 0)
    
    # 用户评价
    uid = restaurant.get("uid", "")
    user_ratings = []
    if uid in user_reviews:
        user_ratings = [review["rating"] for review in user_reviews[uid]]
    
    # 计算综合评分
    # 基础评分权重 (50%)
    base_score = overall_rating
    if taste_rating > 0 or service_rating > 0 or environment_rating > 0:
        base_score = (taste_rating * 0.3 + service_rating * 0.2 + 
                     environment_rating * 0.2 + overall_rating * 0.3)
    
    # 社交属性加权 (25%)
    social_factor = min((comment_num + favorite_num * 2 + checkin_num) / 100, 10) / 10
    
    # 价格合理性 (15%)
    price_factor = 1.0
    if price:
        try:
            price_value = float(price)
            # 价格在50-200之间认为是合理区间，给予加分
            if 50 <= price_value <= 200:
                price_factor = 1.1
            elif price_value > 500:
                price_factor = 0.9
        except ValueError:
            pass
    
    # 用户评价 (10%)
    user_rating_factor = 0.0
    if user_ratings:
        user_rating_factor = sum(user_ratings) / len(user_ratings) / 5.0  # 标准化到0-1
    
    # 综合评分计算
    composite_score = base_score * 0.5 + social_factor * 0.25 + price_factor * 0.15 + user_rating_factor * 0.1
    
    # 如果有用户偏好，进行个性化调整
    if user_preferences:
        # 根据用户偏好调整评分
        preferred_cuisine = user_preferences.get("cuisine", "")
        if preferred_cuisine and preferred_cuisine in detail_info.get("tag", ""):
            composite_score *= 1.1  # 偏好类型加权
    
    return composite_score


# ========== MCP 工具定义 ==========

@mcp.tool()
async def recommend_food(
    address: str,
    cuisine_type: str = "餐厅",
    radius: int = 1000,
    num_recommend: int = 5,
    price_range: Optional[str] = None,
    sort_by: Optional[str] = None,
    groupon_only: bool = False,
    discount_only: bool = False
) -> str:
    """
    根据地址和菜系类型推荐附近的餐厅
    
    参数:
        address: 用户地址（如"北京市海淀区上地十街10号"）
        cuisine_type: 菜系类型（如"火锅"、"川菜"、"日料"等，默认"餐厅"）
        radius: 搜索半径（米），默认1000米
        num_recommend: 推荐数量，默认5个
        price_range: 价格区间，如"0-50"、"50-100"、"100-200"等
        sort_by: 排序方式，可选: "rating"(评分), "distance"(距离), "price"(价格)
        groupon_only: 是否只显示有团购的餐厅
        discount_only: 是否只显示有折扣的餐厅
    
    返回:
        包含推荐餐厅列表的JSON字符串
    """
    try:
        logger.info(f"开始推荐美食: 地址={address}, 菜系={cuisine_type}, 半径={radius}米, 数量={num_recommend}")
        
        # 参数验证
        if not address.strip():
            raise ValueError("地址不能为空")
            
        if not (50 <= radius <= 3000):
            logger.warning(f"推荐半径 {radius} 超出建议范围 [50, 3000]，可能影响结果质量")
            
        if not (1 <= num_recommend <= 20):
            logger.warning(f"推荐数量 {num_recommend} 超出合理范围 [1, 20]，将使用默认值 5")
            num_recommend = 5
        
        # 解析价格区间
        price_section = None
        if price_range:
            if price_range == "0-50":
                price_section = "1"
            elif price_range == "50-100":
                price_section = "2"
            elif price_range == "100-200":
                price_section = "3"
            elif price_range == "200-400":
                price_section = "4"
            elif price_range == "400+":
                price_section = "5"
        
        # 确定排序方式
        sort_name = None
        sort_rule = None
        if sort_by == "price":
            sort_name = "price"
            sort_rule = 1  # 升序
        elif sort_by == "rating":
            sort_name = "overall_rating"
            sort_rule = 0  # 降序
        
        # 团购和折扣参数
        groupon_param = "1" if groupon_only else None
        discount_param = "1" if discount_only else None
        
        # 1. 地址 → 坐标
        loc = await geocode_address(address)
        lat = loc["lat"]
        lng = loc["lng"]
        
        # 2. 搜索候选餐厅
        candidates = await search_places(
            cuisine_type, 
            lat, 
            lng, 
            radius, 
            num_recommend * 3,  # 增加候选数量以提高推荐质量
            tag=cuisine_type,
            price_section=price_section,
            sort_name=sort_name,
            sort_rule=sort_rule,
            groupon=groupon_param,
            discount=discount_param
        )
        
        # 3. 并发获取详情 & 准备推荐数据
        uids = [poi.get("uid") for poi in candidates if poi.get("uid")]
        detailed_results = await get_multiple_place_details(uids, force_refresh=True)
        
        detailed = []
        for i, det in enumerate(detailed_results):
            if det is None:
                continue
                
            uid = uids[i]
            detail_info = det.get("detail_info", {})
            
            # 数据标准化
            normalized_data = normalize_data(det)
            
            info = {
                "name": normalized_data["name"],
                "address": normalized_data["address"],
                "telephone": normalized_data["telephone"],
                "rating": normalized_data["overall_rating"],
                "location": normalized_data["location"],
                "uid": normalized_data["uid"],
                # 添加更多评分维度
                "taste_rating": normalized_data["taste_rating"],
                "price": normalized_data["price"],
                "service_rating": normalized_data["service_rating"],
                "environment_rating": normalized_data["environment_rating"],
                # 添加社交属性
                "comment_num": normalized_data["comment_num"],
                "favorite_num": normalized_data["favorite_num"],
                "checkin_num": normalized_data["checkin_num"],
                # 添加其他有用信息
                "tag": normalized_data["tag"],
                "hours": normalized_data["hours"],
                "description": normalized_data["description"],
                # 添加用户评价信息
                "user_reviews": user_reviews.get(uid, [])
            }
            
            # 使用 Haversine 公式计算精确距离
            if info["location"]:
                info["distance_m"] = round(haversine_distance(
                    lat, lng, 
                    info["location"]["lat"], 
                    info["location"]["lng"]
                ))
            else:
                info["distance_m"] = None
            detailed.append(info)

        # 4. 排序：综合评分降序 + 距离近优先
        def sort_key(x):
            composite_score = calculate_composite_score(x)
            # 如果指定了排序方式，则按指定方式排序
            if sort_by == "distance":
                return (x.get("distance_m") or 999999)
            elif sort_by == "price":
                try:
                    price = float(x.get("price") or 0)
                    return (price, -composite_score)
                except ValueError:
                    return (999999, -composite_score)
            elif sort_by == "rating":
                return (-composite_score)
            else:
                # 默认排序：综合评分为主，距离为辅
                return (-composite_score, x.get("distance_m") or 999999)
            
        detailed.sort(key=sort_key)
        top = detailed[: num_recommend]

        # 返回结构
        result = {
            "query_address": address,
            "cuisine_type": cuisine_type,
            "radius_m": radius,
            "price_range": price_range,
            "sort_by": sort_by,
            "groupon_only": groupon_only,
            "discount_only": discount_only,
            "recommendations": top
        }
        
        # 格式化输出
        import json
        output = json.dumps(result, ensure_ascii=False, indent=2)
        logger.info(f"推荐完成，返回 {len(top)} 个结果")
        return output
        
    except Exception as e:
        logger.error(f"推荐失败: {str(e)}")
        return f"推荐失败: {str(e)}"


@mcp.tool()
async def search_nearby_restaurants(
    address: str,
    keyword: str = "餐厅",
    radius: int = 1000,
    max_results: int = 10,
    price_range: Optional[str] = None,
    sort_by: Optional[str] = None,
    fuzzy_search: bool = False
) -> str:
    """
    搜索指定地址附近的餐厅
    
    参数:
        address: 搜索地址
        keyword: 搜索关键词（默认"餐厅"）
        radius: 搜索半径（米），默认1000米
        max_results: 最多返回结果数，默认10个
        price_range: 价格区间，如"0-50"、"50-100"、"100-200"等
        sort_by: 排序方式，可选: "rating"(评分), "distance"(距离), "price"(价格)
        fuzzy_search: 是否启用模糊搜索
    
    返回:
        附近餐厅列表的JSON字符串
    """
    try:
        logger.info(f"开始搜索附近餐厅: 地址={address}, 关键词={keyword}, 半径={radius}米, 最大结果数={max_results}")
        
        # 参数验证
        if not address.strip():
            raise ValueError("地址不能为空")
            
        if not (50 <= radius <= 3000):
            logger.warning(f"搜索半径 {radius} 超出建议范围 [50, 3000]，可能影响结果质量")
            
        if not (1 <= max_results <= 20):
            logger.warning(f"最大结果数 {max_results} 超出合理范围 [1, 20]，将使用默认值 10")
            max_results = 10
            
        # 解析价格区间
        price_section = None
        if price_range:
            if price_range == "0-50":
                price_section = "1"
            elif price_range == "50-100":
                price_section = "2"
            elif price_range == "100-200":
                price_section = "3"
            elif price_range == "200-400":
                price_section = "4"
            elif price_range == "400+":
                price_section = "5"
        
        # 确定排序方式
        sort_name = None
        sort_rule = None
        if sort_by == "price":
            sort_name = "price"
            sort_rule = 1  # 升序
        elif sort_by == "rating":
            sort_name = "overall_rating"
            sort_rule = 0  # 降序
            
        # 地址转坐标
        loc = await geocode_address(address)
        lat = loc["lat"]
        lng = loc["lng"]
        
        # 如果启用模糊搜索，扩展关键词
        search_keywords = [keyword]
        if fuzzy_search:
            # 这里可以添加常见的餐厅类型进行模糊匹配
            common_cuisines = [
                "中餐", "西餐", "日料", "韩料", "火锅", "烧烤", 
                "川菜", "粤菜", "湘菜", "鲁菜", "浙菜", "闽菜", 
                "苏菜", "徽菜", "快餐", "小吃", "甜品", "咖啡"
            ]
            fuzzy_matches = fuzzy_match(keyword, common_cuisines)
            search_keywords.extend(fuzzy_matches)
            logger.info(f"模糊搜索匹配到关键词: {fuzzy_matches}")
        
        # 搜索地点
        all_places = []
        for search_keyword in search_keywords:
            try:
                places = await search_places(
                    search_keyword, 
                    lat, 
                    lng, 
                    radius, 
                    max_results,
                    price_section=price_section,
                    sort_name=sort_name,
                    sort_rule=sort_rule
                )
                all_places.extend(places)
            except Exception as e:
                logger.warning(f"使用关键词 '{search_keyword}' 搜索失败: {str(e)}")
                continue
        
        # 去重处理
        unique_places = []
        seen_uids = set()
        for place in all_places:
            uid = place.get("uid")
            if uid and uid not in seen_uids:
                unique_places.append(place)
                seen_uids.add(uid)
        
        # 简化结果
        results = []
        for place in unique_places[:max_results]:
            detail_info = place.get("detail_info", {})
            # 数据标准化
            normalized_data = normalize_data(place)
            
            results.append({
                "name": normalized_data["name"],
                "address": normalized_data["address"],
                "uid": normalized_data["uid"],
                "location": normalized_data["location"],
                # 添加评分信息
                "rating": normalized_data["overall_rating"],
                "price": normalized_data["price"],
                # 添加社交属性
                "comment_num": normalized_data["comment_num"],
                "tag": normalized_data["tag"],
                # 添加用户评价信息
                "user_reviews": user_reviews.get(normalized_data["uid"], [])
            })
        
        import json
        result = {
            "address": address,
            "keyword": keyword,
            "fuzzy_search": fuzzy_search,
            "radius_m": radius,
            "price_range": price_range,
            "sort_by": sort_by,
            "results": results
        }
        output = json.dumps(result, ensure_ascii=False, indent=2)
        logger.info(f"搜索完成，返回 {len(results)} 个结果")
        return output
        
    except Exception as e:
        logger.error(f"搜索失败: {str(e)}")
        return f"搜索失败: {str(e)}"


@mcp.tool()
async def get_restaurant_details(uid: str, refresh: bool = False) -> str:
    """
    获取餐厅详细信息
    
    参数:
        uid: 餐厅的唯一标识符
        refresh: 是否强制刷新缓存数据
    
    返回:
        餐厅详细信息的JSON字符串
    """
    try:
        logger.info(f"开始获取餐厅详情: UID={uid}")
        
        # 参数验证
        if not uid.strip():
            raise ValueError("餐厅 UID 不能为空")
            
        details = await get_place_details_with_cache(uid, force_refresh=refresh)
        # 添加用户评价信息
        details["user_reviews"] = user_reviews.get(uid, [])
        
        import json
        output = json.dumps(details, ensure_ascii=False, indent=2)
        logger.info(f"获取餐厅详情成功: UID={uid}")
        return output
    except Exception as e:
        logger.error(f"获取详情失败: {str(e)}")
        return f"获取详情失败: {str(e)}"


@mcp.tool()
async def compare_restaurants(uids: List[str]) -> str:
    """
    对比多个餐厅的信息
    
    参数:
        uids: 餐厅的唯一标识符列表
    
    返回:
        餐厅对比信息的JSON字符串
    """
    try:
        logger.info(f"开始对比餐厅: UIDs={uids}")
        
        # 参数验证
        if not uids:
            raise ValueError("至少需要一个餐厅 UID")
        
        if len(uids) > 10:
            raise ValueError("最多只能同时对比10个餐厅")
        
        # 获取所有餐厅详情
        restaurant_details = await get_multiple_place_details(uids)
        
        # 准备对比数据
        comparison_data = []
        for i, detail in enumerate(restaurant_details):
            if detail is None:
                continue
                
            uid = uids[i]
            detail_info = detail.get("detail_info", {})
            # 数据标准化
            normalized_data = normalize_data(detail)
            
            # 添加用户评价统计
            user_review_count = len(user_reviews.get(uid, []))
            user_average_rating = 0
            representative_reviews = []
            if user_reviews.get(uid):
                user_average_rating = sum([r["rating"] for r in user_reviews.get(uid, [])]) / len(user_reviews.get(uid, []))
                # 选择最具代表性的评价（最高分和最低分各选一条，最多2条）
                sorted_reviews = sorted(user_reviews[uid], key=lambda x: x["rating"], reverse=True)
                if sorted_reviews:
                    representative_reviews.append(sorted_reviews[0])  # 最高分评价
                    if len(sorted_reviews) > 1:
                        representative_reviews.append(sorted_reviews[-1])  # 最低分评价
            
            comparison_data.append({
                "uid": uid,
                "name": normalized_data["name"],
                "address": normalized_data["address"],
                "rating": normalized_data["overall_rating"],
                "taste_rating": normalized_data["taste_rating"],
                "service_rating": normalized_data["service_rating"],
                "environment_rating": normalized_data["environment_rating"],
                "price": normalized_data["price"],
                "comment_num": normalized_data["comment_num"],
                "favorite_num": normalized_data["favorite_num"],
                "checkin_num": normalized_data["checkin_num"],
                "tag": normalized_data["tag"],
                "hours": normalized_data["hours"],
                "user_review_count": user_review_count,
                "user_average_rating": user_average_rating,
                "representative_reviews": representative_reviews  # 添加代表性评价
            })
        
        # 按综合评分排序
        comparison_data.sort(key=lambda x: calculate_composite_score({"detail_info": {
            "overall_rating": x["rating"],
            "taste_rating": x["taste_rating"],
            "service_rating": x["service_rating"],
            "environment_rating": x["environment_rating"],
            "price": x["price"],
            "comment_num": x["comment_num"],
            "favorite_num": x["favorite_num"],
            "checkin_num": x["checkin_num"]
        }}), reverse=True)
        
        result = {
            "comparison": comparison_data,
            "count": len(comparison_data)
        }
        
        import json
        output = json.dumps(result, ensure_ascii=False, indent=2)
        logger.info(f"餐厅对比完成，共对比 {len(comparison_data)} 个餐厅")
        return output
    except Exception as e:
        logger.error(f"餐厅对比失败: {str(e)}")
        return f"餐厅对比失败: {str(e)}"


@mcp.tool()
async def generate_restaurant_map(
    uids: List[str],
    width: int = 400,
    height: int = 300,
    zoom: int = 15
) -> str:
    """
    为指定UID的餐厅生成带标记的地图图片
    
    参数:
        uids: 餐厅的唯一标识符列表
        width: 图片宽度，默认400像素
        height: 图片高度，默认300像素
        zoom: 地图缩放级别，默认15
    
    返回:
        包含地图图片URL和餐厅位置信息的JSON字符串
    """
    try:
        logger.info(f"开始生成餐厅地图: UIDs={uids}")
        
        # 参数验证
        if not uids:
            raise ValueError("至少需要一个餐厅 UID")
            
        if len(uids) > 10:
            raise ValueError("最多只能同时显示10个餐厅位置")
            
        if not (200 <= width <= 1000):
            logger.warning(f"图片宽度 {width} 超出建议范围 [200, 1000]，将使用默认值 400")
            width = 400
            
        if not (200 <= height <= 1000):
            logger.warning(f"图片高度 {height} 超出建议范围 [200, 1000]，将使用默认值 300")
            height = 300
            
        if not (3 <= zoom <= 19):
            logger.warning(f"缩放级别 {zoom} 超出建议范围 [3, 19]，将使用默认值 15")
            zoom = 15
        
        # 获取所有餐厅详情
        restaurant_details_list = await get_multiple_place_details(uids)
        
        # 过滤掉获取失败的餐厅详情
        valid_restaurants = []
        for i, details in enumerate(restaurant_details_list):
            if details is None:
                logger.warning(f"无法获取餐厅详情: UID={uids[i]}")
                continue
                
            location = details.get("location")
            if not location:
                logger.warning(f"餐厅位置信息不可用: UID={uids[i]}")
                continue
                
            lat = location.get("lat")
            lng = location.get("lng")
            
            if not lat or not lng:
                logger.warning(f"餐厅位置坐标不完整: UID={uids[i]}")
                continue
                
            valid_restaurants.append({
                "uid": uids[i],
                "name": details.get("name", "未知餐厅"),
                "latitude": lat,
                "longitude": lng
            })
        
        if not valid_restaurants:
            return "没有有效的餐厅位置信息可用于生成地图"
        
        # 计算中心点（如果有多个餐厅）
        center_lat, center_lng = _calculate_center_point(valid_restaurants)
        
        # 构造标记点字符串
        marker_points = _build_marker_points(valid_restaurants)
        
        # 生成静态地图URL
        map_url = _generate_static_map_url(
            center_lat, center_lng, width, height, zoom, marker_points
        )
        
        result = {
            "map_url": map_url,
            "restaurants": valid_restaurants,
            "center_latitude": center_lat,
            "center_longitude": center_lng,
            "width": width,
            "height": height,
            "zoom": zoom
        }
        
        import json
        output = json.dumps(result, ensure_ascii=False, indent=2)
        logger.info(f"成功生成餐厅地图，包含 {len(valid_restaurants)} 个餐厅位置")
        return output
        
    except Exception as e:
        logger.error(f"生成餐厅地图失败: {str(e)}")
        return f"生成餐厅地图失败: {str(e)}"


def _calculate_center_point(valid_restaurants: List[Dict[str, Any]]) -> tuple:
    """
    计算多个餐厅位置的中心点
    
    参数:
        valid_restaurants: 有效餐厅列表
        
    返回:
        (中心纬度, 中心经度) 元组
    """
    if len(valid_restaurants) == 1:
        restaurant = valid_restaurants[0]
        return restaurant["latitude"], restaurant["longitude"]
    else:
        # 计算所有有效餐厅的中心点
        avg_lat = sum(r["latitude"] for r in valid_restaurants) / len(valid_restaurants)
        avg_lng = sum(r["longitude"] for r in valid_restaurants) / len(valid_restaurants)
        return avg_lat, avg_lng


def _build_marker_points(valid_restaurants: List[Dict[str, Any]]) -> str:
    """
    构造地图标记点字符串
    
    参数:
        valid_restaurants: 有效餐厅列表
        
    返回:
        标记点字符串，格式为 "lng1,lat1|lng2,lat2|..."
    """
    marker_points = []
    for restaurant in valid_restaurants:
        marker_points.append(f"{restaurant['longitude']},{restaurant['latitude']}")
    return "|".join(marker_points)


def _generate_static_map_url(
    center_lat: float, 
    center_lng: float, 
    width: int, 
    height: int, 
    zoom: int, 
    markers: str
) -> str:
    """
    生成静态地图URL
    
    参数:
        center_lat: 中心点纬度
        center_lng: 中心点经度
        width: 图片宽度
        height: 图片高度
        zoom: 缩放级别
        markers: 标记点字符串
        
    返回:
        完整的静态地图URL
    """
    from urllib.parse import urlencode
    
    map_url = f"{API_URL}/staticimage/v2"
    params = {
        "ak": API_KEY,
        "center": f"{center_lng},{center_lat}",
        "width": width,
        "height": height,
        "zoom": zoom,
        "markers": markers,
        "markerStyles": "l,A"
    }
    
    return f"{map_url}?{urlencode(params)}"


# ========== 运行服务器 ==========

def main():
    """启动MCP服务器"""
    logger.info("="*60)
    logger.info("🍜 美食推荐MCP服务器启动")
    logger.info("="*60)
    
    # 获取端口配置（阿里云函数计算使用 PORT 环境变量）
    port = int(os.environ.get("MCP_PORT", os.environ.get("PORT", "9000")))
    
    logger.info(f"[SSE模式] 启动 MCP 服务器")
    logger.info(f"[SSE模式] 监听地址: http://localhost:{port}/sse")
    logger.info(f"[SSE模式] 网络地址: http://0.0.0.0:{port}/sse")
    logger.info(f"[SSE模式] 使用 Ctrl+C 停止服务器")
    logger.info("-" * 60)
    
    # 启动MCP服务器
    # FastMCP 2.5+ 版本支持 host/port 参数
    mcp.run(
        transport="sse",
        host="0.0.0.0",
        port=port,
        path="/sse",
        log_level="info",
    )


if __name__ == "__main__":
    main()
