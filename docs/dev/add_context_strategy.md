# 如何新增一个 Context Strategy（以 procc 为例）

本文说明如何在 AICGSecEval 中新增/维护一个上下文策略（context strategy），并保证：
- 可配置（CLI 参数可控）
- 可复现（固定输入得到稳定输出）
- 可切换（通过 retrieval jsonl 文件切换）
- 异常可解释（失败有清晰日志与降级行为）

---

## 1. 关键入口与职责划分

### 1.1 run_data_retrieval_bm25.py（离线生成检索数据入口）
职责：
- 读取 dataset json
- 根据 `--context_strategy` 选择策略
- 生成 `data/*_context_bm25_<strategy>.jsonl`，供 invoke 阶段消费

### 1.2 bench/context_manager.py（策略注册与组装）
职责：
- 注册策略名（如 `procc`）
- 执行上下文构建：crop → retrieve → assemble
- 统一输出 schema：`contexts` 列表 + meta（可选）

### 1.3 bench/bm25_retrieval.py（BM25 检索器）
职责：
- 建索引（缓存/复用）
- 执行检索并返回 top-k + score
- 处理空结果/异常（不崩溃，返回可降级结构）

---

## 2. 策略输入 / 输出约定（必须稳定）

### 2.1 输入（建议最小集合）
- instance 基本信息：instance_id / repo / commit / target_file / (可选) target_function / vulnerability_desc
- 策略配置：topk / max_context_tokens(or chars) / 去重策略 / 是否启用模型等
- 检索器：BM25 实例或检索函数

### 2.2 输出（写入 jsonl，invoke 必须可消费）
每条 jsonl 至少包含：
- `instance_id`
- `contexts`: list[context_item]

每个 context_item 建议包含：
- `file_path`：上下文来源文件
- `content`：文本内容
- `score`：检索得分（BM25）
- `meta`（可选）：函数名、起止行、来源类型（file/function/summary）

---

## 3. 新增策略的落地步骤（推荐流程）

### Step 1：实现策略逻辑（crop/retrieve/assemble）
建议显式拆分三个阶段，便于调试与测试：
- crop：产出可检索的候选文本（文件片段/函数片段/摘要等）
- retrieve：BM25 top-k 检索（支持空结果）
- assemble：拼装 contexts（长度控制、去重、排序）

### Step 2：在 bench/context_manager.py 注册策略名
确保：
- CLI 传入 `--context_strategy <name>` 能路由到该策略
- 未知策略名时抛出清晰错误（包含可选策略列表）

### Step 3：在 run_data_retrieval_bm25.py 接入 CLI 参数
确保：
- `--context_strategy` 中包含新策略名
- 策略专属参数（例如 `--procc_model`）能传递到策略实现
- 输出文件名包含策略名，避免覆盖：
  - `data/<dataset>_context_bm25_<strategy>.jsonl`

### Step 4：加入最小测试与冒烟验证
- 单元测试：空输入/空检索/文件缺失不崩溃
- 冒烟：用 1~2 条样本跑通到 `image_status_check`

---

## 4. 如何切换 Context Strategy

invoke 阶段不直接传 strategy，而是通过 `--retrieval_data_path` 指向不同 jsonl 来切换策略：

1) 先生成 procc 的 retrieval jsonl：
```bash
python run_data_retrieval_bm25.py \
  --input_file data/data_v2.json \
  --context_strategy procc \
  --procc_model <MODEL>
```

  2.invoke 指向对应 jsonl，并建议 batch_id 带 strategy，避免产物混淆：

```
python invoke.py \
  --batch_id procc_<model>_<date> \
  --retrieval_data_path data/data_v2_context_bm25_procc.jsonl \
  ...
```