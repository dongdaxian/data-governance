# 向量检索模块使用说明

## 队友快速上手（3 步）

> 你只需要跑 `scripts/vector_build.py`，不涉及 LLM 调用。

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 .env（项目根目录）

```
MILVUS_URI=http://你的Milvus地址:19530
MILVUS_TOKEN=root:你的密码
```

- **有 GPU**：加 `EMBED_DEVICE=cuda`，全量约 5-10 分钟
- **无 GPU**：默认 CPU，全量约 2-3 小时
- **有梯子/VPN**：默认 `MILVUS_PROXY=auto` 自动检测；连不上则手动填 `MILVUS_PROXY=http://127.0.0.1:7890`
- **无代理**：加 `MILVUS_PROXY=none`
- **Milvus 白名单**：如果你的 IP 不在白名单里会连接超时，联系管理员加白名单

### 3. 运行

```bash
# 先测试 10 条/类型
python scripts/vector_build.py --limit 10

# 没问题后跑全量
python scripts/vector_build.py

# 如果之前跑过旧版（单集合 dict_non_enum），清理旧集合
python scripts/vector_build.py --cleanup-legacy
```

首次运行会自动从 hf-mirror.com 下载 bge-large-zh-v1.5 模型（约 1.3GB），之后走本地缓存。

---

## 命令参数

```bash
python scripts/vector_build.py [选项]
  --limit N          仅处理前 N 条/类型（测试用）
  --dry-run          仅向量化，不写入 Milvus
  --input PATH       自定义输入 Excel 路径
  --cleanup-legacy   删除旧的 dict_non_enum 集合
  --no-backup        不生成 Parquet 备份
```

## 在代码中调用检索

```python
from common.vector_store import search

# field_type 决定在哪个 collection 里搜
results = search("客户号", "客户的唯一编号", top_k=10, field_type="编码类")
for r in results:
    print(r["standard_id"], r["name_text"], r["dense_score"], r["sparse_score"], r["source"])
```

## 集合结构

按字段所属类型分 5 个集合，每个 schema 相同（7 字段）：

| 字段所属类型 | 集合名 |
|---|---|
| 编码类 | dict_encode |
| 文本类 | dict_text |
| 数值类 | dict_number |
| 日期时间类 | dict_datetime |
| 标志类 | dict_flag |

字段：standard_id（主键）、name_text、name_dense(1024)、name_sparse(BM25)、meaning_text、meaning_dense(1024)、meaning_sparse(BM25)。

检索逻辑：稠密 top10（HNSW+COSINE，名称+含义各 0.5）+ 稀疏 top10（BM25，名称+含义各 0.5）-> 合并去重，最多 20 条。

## 本地备份

稠密向量按类型备份到 `data/vector_backup/<集合名>.parquet`，Milvus 试用期到期后可用此文件恢复。
