# 向量检索模块使用说明

## 快速开始（3 步）

1. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

2. **配置 .env**（项目根目录创建）
   ```
   MILVUS_URI=http://你的Milvus地址:19530
   MILVUS_TOKEN=root:你的密码
   ```
   - 有 GPU：加 `EMBED_DEVICE=cuda`
   - 无代理：加 `MILVUS_PROXY=none`

3. **运行**
   ```bash
   # 先测试 10 条
   python scripts/vector_build.py --limit 10
   # 确认没问题后跑全量
   python scripts/vector_build.py
   ```

---

## 功能概述

对非代码枚举类字典（约 25,492 条）做向量化，支持「新字段能否复用已有字典」的语义匹配检索。

- 稠密向量：bge-large-zh-v1.5（1024 维，语义检索）
- 稀疏向量：Milvus 内置 BM25 Function（关键词检索）
- 检索方式：稠密 top10 + 稀疏 top10 -> 合并去重，共返回最多 20 条

## 文件结构

```
项目根目录/
  config.py              # 全局配置（Milvus 连接、模型参数等）
  common/
    vector_store.py      # 核心模块：向量化 + 存储 + 检索 + 备份
  scripts/
    vector_build.py      # 一次性脚本：从 Excel 构建向量库
  data/
    dictionary_mock/
      全量字典_最终.xlsx   # 数据源
    vector_backup/        # 稠密向量 Parquet 备份（自动生成）
```

## 可选配置（环境变量）

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `MILVUS_PROXY` | `auto` | `auto`=自动检测系统代理，`none`=不使用代理，或直接填代理地址 |
| `MILVUS_COLLECTION` | `dict_non_enum` | Milvus 集合名称 |
| `EMBED_DEVICE` | `cpu` | 向量化设备：`cpu` 或 `cuda` |
| `EMBED_MODEL_NAME` | `BAAI/bge-large-zh-v1.5` | 向量模型名称 |

## 命令参数

```bash
python scripts/vector_build.py [选项]
  --limit N        仅处理前 N 条（测试用）
  --dry-run        仅向量化，不写入 Milvus
  --input PATH     自定义输入 Excel 路径
  --collection NAME  自定义集合名
  --no-backup      不生成 Parquet 备份
```

## 在代码中调用检索

```python
from common.vector_store import search

results = search("客户号", "客户的唯一编号", top_k=10)
for r in results:
    print(r["standard_id"], r["name_text"], r["dense_score"], r["sparse_score"], r["source"])
```

## 不同环境适配

- **有 GPU**：`.env` 加 `EMBED_DEVICE=cuda`，全量约 5-10 分钟
- **无 GPU（CPU）**：默认即 CPU 模式，全量约 2-3 小时
- **有 VPN/梯子**：默认 `auto` 自动检测；检测失败则手动填 `MILVUS_PROXY=http://127.0.0.1:7890`
- **无代理**：`.env` 加 `MILVUS_PROXY=none`

## 模型下载

首次运行自动从镜像（hf-mirror.com）下载 bge-large-zh-v1.5（约 1.3GB），缓存到本地。下载失败可手动设镜像或离线模式：
```bash
set HF_ENDPOINT=https://hf-mirror.com
# 或已有缓存强制离线
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
```

## Schema 说明

集合 `dict_non_enum` 共 7 个字段：standard_id（主键）、name_text、name_dense(1024)、name_sparse(BM25)、meaning_text、meaning_dense(1024)、meaning_sparse(BM25)。

## 检索逻辑

```
输入：query_name + query_meaning
  |
  |-- 稠密（HNSW + COSINE）
  |     name_dense + meaning_dense 各 0.5 权重 -> top10
  |
  |-- 稀疏（SPARSE_INVERTED_INDEX + BM25）
  |     name_sparse + meaning_sparse 各 0.5 权重 -> top10
  |
  v
合并去重（按 standard_id），最多 20 条
```

## 本地备份

稠密向量自动备份到 `data/vector_backup/dense_vectors.parquet`。Milvus 试用期到期后可用此文件恢复数据。

## 常见问题

- **NumPy 2.x 报错**：代码已内置兼容处理，无需额外操作
- **连接 Milvus 超时**：检查网络和白名单；代码内置 5 次指数退避重试
- **重建集合**：
  ```python
  from common.vector_store import get_client, drop_collection, create_collection
  client = get_client()
  drop_collection(client)
  create_collection(client)
  ```
