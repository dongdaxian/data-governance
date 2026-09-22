# 向量检索模块使用说明

## 队友快速上手（3 步）

> 你只需要跑 `scripts/vector_build.py`，不涉及 LLM 调用。

### 1. 安装依赖（Python 3.11）

```bash
conda env create -f env.lock.yml
conda activate data-governance
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

# 干净重建前，先删除全部类型集合
python scripts/vector_build.py --cleanup
```

首次运行会自动从 hf-mirror.com 下载 bge-large-zh-v1.5 模型（约 1.3GB），之后走本地缓存。

---

## 命令参数

```bash
python scripts/vector_build.py [选项]
  --limit N          仅处理前 N 条/类型（测试用）
  --dry-run          仅向量化，不写入 Milvus
  --input PATH       自定义输入 Excel 路径
  --cleanup          删除全部类型集合（dict_encode/text/number/datetime/flag）
```

## 在代码中调用检索

```python
from common.vector_store import search

# field_type 决定在哪个 collection 里搜
results = search("客户号", "客户的唯一编号", top_k=10, field_type="编码类")
for r in results:
    print(r["standard_id"], r["name_text"], r["dense_score"], r["name_sparse_score"], r["meaning_sparse_score"], r["source"])
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

检索逻辑（混合检索，三路并集去重）：
- 稠密主路：name_dense + meaning_dense 各取 top_k×5 子窗口，按名称 0.6 / 含义 0.4 权重合并得分后取 top_k（HNSW+COSINE）
- 稀疏补充路：名称 BM25 取 top_k、含义 BM25 取 top_k，两路独立，召回稠密路漏掉的字面强匹配标准
- 三路按 standard_id 去重并集（稠密优先，稀疏补充漏检项）
