# 模型中转服务

跨平台模型中转服务，通过定时测试上游中转站延迟，选择最优路径转发客户端请求。

## 功能特性

- **中转站管理**：可视化配置多个上游 API 中转站
- **模型别名**：为不同中转站的模型设置统一别名
- **定时测速**：自动测试所有已启用模型的连通性和延迟
- **智能路由**：自动选择延迟最低的中转站处理请求
- **OpenAI 兼容**：提供标准的 OpenAI API 接口
- **多 Key 支持**：支持多个 API Key 轮询，避免 TPM 限制

## 快速开始

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务（在 model-relay-service 目录下）
cd model-relay-service
python -m app.main

# 3. 访问 WebUI
open http://localhost:8000/ui/providers
```

### Docker 部署

```bash
# 1. 构建镜像
docker-compose build

# 2. 启动服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 停止服务
docker-compose down
```

## 配置说明

所有配置存储在 `runtime/` 目录：

| 文件 | 说明 |
|------|------|
| `runtime/providers.json` | 中转站配置 |
| `runtime/aliases.json` | 模型别名映射 |
| `runtime/settings.json` | 系统参数 |
| `runtime/test_results.db` | 测试结果数据库 |

## API 接口

### OpenAI 兼容接口

```bash
# 获取模型列表
curl http://localhost:8000/v1/models

# 对话补全（非流式）
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-alias-name",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# 对话补全（流式）
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-alias-name",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

## WebUI 界面

- `/ui/providers` - 中转站管理
- `/ui/models` - 模型管理
- `/ui/aliases` - 别名管理
- `/ui/test` - 测试控制
- `/ui/history` - 测试历史
- `/ui/settings` - 系统设置

## 环境要求

- Python 3.9+
- Docker & docker-compose（容器化部署）
