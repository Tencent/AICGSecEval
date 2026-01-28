# 上下文策略：procc

`procc` 是一种上下文构建策略，贯穿 **裁剪（crop）→ 检索（retrieve）→ 组装（assemble）→ 可配置（config）** 的完整链路。
该策略由 `run_data_retrieval_bm25.py` 触发，并在 `bench/context_manager.py` 中被注册/路由，检索能力由 `bench/bm25_retrieval.py` 提供。

---

## 1. 目标与设计动机

在补丁生成任务中，LLM 需要足够的代码上下文（脆弱点附近实现、相关结构体/宏、调用关系等）。
`procc` 的核心目标是：
- **在上下文长度受限的情况下**，尽可能将“与漏洞相关”的片段放入上下文；
- 通过更稳定的检索与拼装策略，提升补丁的可应用性与漏洞修复率；
- 让策略具备**可复现、可配置、可切换**的实验能力。

---

## 2. 工作流（Crop → Retrieve → Assemble）

### 2.1 裁剪（Crop）
- 输入：样本指定的 repo / commit / 目标文件或函数线索
- 输出：用于建立 BM25 索引/检索的候选文本（例如：文件内容、函数片段、函数摘要等）
- 裁剪要点：
  - 控制单条文本长度（避免超长文件导致索引/检索失真）
  - 保留关键结构：函数签名、宏定义、结构体定义、与漏洞点邻近片段

> 说明：当前 `procc` 支持通过 `--procc_model` 引入模型参与“候选上下文生成/压缩”（例如函数摘要/候选片段生成），以提高检索可命中性。

### 2.2 检索（Retrieve）
- 检索器：BM25（实现位于 `bench/bm25_retrieval.py`）
- 索引：`run_data_retrieval_bm25.py` 会在 outputs 下生成/复用索引缓存
- 输入：query（通常由样本元信息构造，例如漏洞描述/目标函数名/文件路径等）
- 输出：top-k 上下文片段（包含 score）

### 2.3 组装（Assemble）
- 组装器：`bench/context_manager.py`
- 输出 schema（写入 jsonl，供 invoke 阶段消费）建议最少包含：
  - `instance_id`
  - `contexts`: list
    - `file_path`
    - `content`
    - `score`
    - （可选）`meta`：如函数名、起止行、来源类型（file/function/summary）

---

## 3. 可配置参数（Config）

### 3.1 生成检索数据（run_data_retrieval_bm25.py）
关键参数：
- `--input_file`：数据集 json
- `--context_strategy procc`：选择 procc 策略
- `--procc_model <model_name>`：procc 使用的模型

示例：
```bash
python run_data_retrieval_bm25.py \
  --input_file data/data_v2.json \
  --context_strategy procc \
  --procc_model deepseek-r1-250528