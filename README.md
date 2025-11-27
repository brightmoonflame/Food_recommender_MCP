# 美食推荐 MCP 服务器

这是一个基于 FastMCP 的美食推荐服务器，提供基于百度地图 API 的餐厅搜索和推荐功能。

## 功能特性

本 MCP 服务器提供以下五个工具：

1. **recommend_food** - 根据地址和菜系类型推荐附近的餐厅
   - 参数：
     - `address`: 用户地址（如"北京市海淀区上地十街10号"）
     - `cuisine_type`: 菜系类型（如"火锅"、"川菜"、"日料"等，默认"餐厅"）
     - `radius`: 搜索半径（米），默认1000米
     - `num_recommend`: 推荐数量，默认5个
     - `price_range`: 价格区间，如"0-50"、"50-100"、"100-200"等
     - `sort_by`: 排序方式，可选: "rating"(评分), "distance"(距离), "price"(价格)
     - `groupon_only`: 是否只显示有团购的餐厅
     - `discount_only`: 是否只显示有折扣的餐厅
   - 返回：包含推荐餐厅列表的详细信息，包括名称、地址、电话、评分、距离等

2. **search_nearby_restaurants** - 搜索指定地址附近的餐厅
   - 参数：
     - `address`: 搜索地址
     - `keyword`: 搜索关键词（默认"餐厅"）
     - `radius`: 搜索半径（米），默认1000米
     - `max_results`: 最多返回结果数，默认10个
     - `price_range`: 价格区间，如"0-50"、"50-100"、"100-200"等
     - `sort_by`: 排序方式，可选: "rating"(评分), "distance"(距离), "price"(价格)
     - `fuzzy_search`: 是否启用模糊搜索
   - 返回：附近餐厅列表的基本信息

3. **get_restaurant_details** - 获取餐厅详细信息
   - 参数：
     - `uid`: 餐厅的唯一标识符
     - `refresh`: 是否强制刷新缓存数据
   - 返回：餐厅的详细信息

4. **compare_restaurants** - 对比多个餐厅的信息
   - 参数：
     - `uids`: 餐厅的唯一标识符列表
   - 返回：餐厅对比信息，包括评分、价格、评论数等

5. **generate_restaurant_map** - 生成指定餐厅在地图上的静态图片
   - 参数：
     - `uids`: 餐厅的唯一标识符列表
     - `width`: 图片宽度，默认400像素
     - `height`: 图片高度，默认300像素
     - `zoom`: 地图缩放级别，默认15
   - 返回：包含地图图片URL和餐厅位置信息

## 环境配置

### 1. 安装依赖

```bash
pip install fastmcp httpx python-dotenv
```

### 2. 配置 API Key

在项目根目录创建 `.env` 文件，添加以下内容：

```
BAIDU_MAPS_API_KEY=your_baidu_maps_api_key_here
```

请访问 [百度地图开放平台](https://lbsyun.baidu.com/) 申请 API Key。

## 使用方法

### 快速测试

运行测试脚本验证服务器功能：

```bash
python test_mcp.py
```

### 两种运行模式

#### 模式 1: Stdio 模式（推荐日常使用）

**特点：** Claude Desktop 自动启动和管理，无需手动操作

配置 Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`)：
```json
{
  "mcpServers": {
    "food-recommender": {
      "command": "python",
      "args": ["Food_recommender_MCP\\mcp_server.py"]
    }
  }
}
```

#### 模式 2: SSE 模式（推荐开发测试）

**特点：** 通过 HTTP 端口访问，方便调试和测试

1. 启动 SSE 服务器：
```bash
python mcp_server.py --sse --port 8000
# 或双击 run_sse_server.bat
```

2. 配置 Claude Desktop：
```json
{
  "mcpServers": {
    "Food_recommender_MCP": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

3. 测试连接：
```bash
python test_sse_simple.py
```

**详细说明：**
- Stdio 模式使用指南：见本文档
- SSE 模式使用指南：见 [SSE_USAGE.md](SSE_USAGE.md)
- SSE 快速开始：见 [QUICKSTART_SSE.md](QUICKSTART_SSE.md)

### 配置到 Claude Desktop

在您的 MCP 客户端配置文件中添加：

```json
{
  "mcpServers": {
    "food-recommender": {
      "command": "python",
      "args": [
        "Food_recommender_MCP\\mcp_server.py"
      ],
      "env": {
        "BAIDU_MAPS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### Claude Desktop 配置步骤

1. 找到 Claude Desktop 配置文件：`%APPDATA%\Claude\claude_desktop_config.json`

2. 编辑该文件，添加以下配置：

```json
{
  "mcpServers": {
    "food-recommender": {
      "command": "python",
      "args": [
        "Food_recommender_MCP\\mcp_server.py"
      ]
    }
  }
}
```

**注意事项：**
- 确保 Python 路径正确（如果使用 conda 环境，需要使用完整路径）
- 确保 `.env` 文件在 `g:\food_mcp` 目录下
- 配置完成后重启 Claude Desktop

3. 如果使用 conda 环境，配置应该是：

```json
{
  "mcpServers": {
    "food-recommender": {
      "command": "C:/ProgramData/Anaconda3/envs/steam_mcp/python.exe",
      "args": [
        "Food_recommender_MCP\\mcp_server.py"
      ]
    }
  }
}
```

## 使用示例

### 示例 1: 推荐火锅店

```
请在"北京市海淀区上地十街10号"附近推荐火锅店
```

服务器将调用 `recommend_food` 工具，返回附近最好的火锅店列表，按评分和距离排序。

### 示例 2: 搜索附近餐厅

```
搜索"北京市朝阳区三里屯"附近的日料店
```

服务器将调用 `search_nearby_restaurants` 工具，返回附近的日料店列表。

### 示例 3: 查看餐厅详情

```
查看 uid 为 "xxx" 的餐厅详细信息
```

服务器将调用 `get_restaurant_details` 工具，返回该餐厅的详细信息。

### 示例 4: 对比餐厅

```
对比这几个餐厅: uid1, uid2, uid3
```

服务器将调用 `compare_restaurants` 工具，返回这些餐厅的对比信息。

### 示例 5: 生成餐厅地图

```
生成这几个餐厅的地图: uid1, uid2
```

服务器将调用 `generate_restaurant_map` 工具，返回包含这些餐厅位置的地图图片。

## 项目结构

```
food_mcp/
├── mcp_server.py      # FastMCP 服务器实现
├── test_mcp.py        # MCP 功能测试脚本
├── test_sse_client.py # SSE 客户端测试脚本
├── test_sse_simple.py # 简单 SSE 测试脚本
├── .env              # 环境变量配置（需要创建）
└── README.md         # 本文件
```

## 技术栈

- **FastMCP**: MCP 服务器框架
- **HTTPX**: 异步 HTTP 客户端
- **百度地图 API**: 地理编码和地点搜索服务
- **Python 3.11+**: 运行环境

## 注意事项

1. 确保百度地图 API Key 已正确配置且有足够的配额
2. 搜索半径建议设置在 500-3000 米之间
3. API 调用可能受限于百度地图的频率限制
4. 距离计算使用 Haversine 公式，相对准确

## 许可证

MIT License
