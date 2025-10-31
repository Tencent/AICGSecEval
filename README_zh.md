<p align="center">
    <h1 align="center"><img vertical-align=“middle” width="400px" src="img/title_header.png" alt="A.S.E"/></h1>
</p>

<h4 align="center">
    <p>
        <!-- <a href="https://tencent.github.io/xxxx/">Documentation</a> | -->
        <a href="#">中文</a> |
        <a href="./README.md">English</a>
    <p>
</h4>

<p align="center">
  <a href="https://github.com/Tencent/AICGSecEval">
        <img alt="Release" src="https://img.shields.io/github/v/release/Tencent/AICGSecEval?color=green">
    </a>
    <a href="https://github.com/Tencent/AICGSecEval">
        <img alt="GitHub Stars" src="https://img.shields.io/github/stars/Tencent/AICGSecEval?color=gold">
    </a>
    <a href="https://github.com/Tencent/AICGSecEval">
        <img alt="GitHub Stars" src="https://img.shields.io/github/forks/Tencent/AICGSecEval?color=gold">
    </a>
    <!-- <a href="https://github.com/Tencent/AICGSecEval">
        <img alt="GitHub downloads" src="https://img.shields.io/github/downloads/Tencent/AICGSecEval/total">
    </a> -->
</p>


<br>
<p align="center">
    <h3 align="center">🚀 「腾讯悟空代码安全团队」推出的行业首个项目级 AI 生成代码安全性评测框架</h3>
</p>


**A.S.E（AICGSecEval）** 提供了全新的项目级 AI 生成代码安全评测基准，旨在通过模拟真实世界 AI 编程过程，评估 AI 生成代码在安全性方面的表现：
* **代码生成任务**源自真实世界 GitHub 项目与权威 CVE 漏洞，确保评测任务的实战性和安全敏感性；
* **代码生成过程**自动提取项目级代码上下文，精准模拟真实 AI 编程场景；
* **代码安全评估**集成了动静态协同的评估套件，兼顾检测广度与验证精度，显著提升安全评测的科学性与实用价值。

<p>
我们致力于将 A.S.E（AICGSecEval）打造成开放、可复现、持续进化的社区项目，欢迎通过 Star、Fork、Issue、Pull Request 参与数据扩展与评测改进，共同推动项目迭代与完善。您的关注与贡献将助力 A.S.E 持续成长，促进大模型在 AI 编程安全领域的产业落地与学术研究。
</p>

<p align="center">
  <a href="https://github.com/Tencent/AICGSecEval">
      <img src="https://img.shields.io/badge/⭐-点亮 Star-yellow?style=flat&logo=github" alt="点亮Star">
  </a>
  <!-- A.S.E 官网 -->
  <a href="https://aicgseceval.tencent.com/home">
    <img src="https://img.shields.io/badge/🌐-A.S.E 官网-blue?style=flat&logo=&logoColor=white" alt="访问官网">
  </a>
  <!-- 评测结果 -->
  <a href="https://aicgseceval.tencent.com/home">
    <img src="https://img.shields.io/badge/📊-评测结果-success?style=flat&logo=tencent&logoColor=white" alt="评测结果">
  </a>
  <!-- 最新动态 -->
  <a href="https://aicgseceval.tencent.com/home">
    <img src="https://img.shields.io/badge/📰-A.S.E 最新动态-orange?style=flat&logo=&logoColor=white" alt="最新动态">
  </a>
  <a href="https://arxiv.org/abs/2508.18106" target="_blank">
    <img src="https://img.shields.io/badge/📄-学术论文-red?style=flat-rounded&logo=arxiv&logoColor=white" alt="学术论文">
  </a>
  <!-- HuggingFace 数据集 -->
  <!-- <a href="https://huggingface.co/datasets/tencent/AICGSecEval" target="_blank">
    <img src="https://img.shields.io/badge/🤗-数据集-yellow?style=flat-rounded&logo=huggingface&logoColor=black" alt="Hugging Face 数据集"> -->
  <!-- </a> -->
</p>



## 目录
- [🧱 评测框架](#-评测框架)
- [✨ 亮点设计](#-亮点设计)
- [🚀 使用 A.S.E](#-使用-ase)
  - [运行环境配置](#运行环境配置)
  - [运行示例](#运行示例)
  - [LLM 调用支持](#llm-调用支持)
  - [加入排行榜](#加入排行榜)
- [💭 未来计划](#-未来计划)
- [🤝 贡献](#-贡献)
- [🙏 致谢](#-致谢)
- [📄 许可证](#-许可证)


## ✨ 关键设计

| 关键模块 | 设计原则 |
|:--------|:------------|
| 代码生成任务 | 设计原则 |



A.S.E 构建了多维度评估体系，全面检测 LLM 的代码生成能力：
* **代码安全性**：专家级定制检测，由安全专家为每个 CVE 定制专属漏洞检测规则，保障评估的准确性与针对性。
* **代码质量**：项目兼容性验证，生成代码需能够成功合入原项目并通过 SAST 工具的语法检查。
* **生成稳定性**：多轮输出一致性测试，每条测试数据会在相同输入条件下生成三轮结果进行对比分析。


## 🧱 评测框架

 <img src="./img/arch_cn.svg" style="display: block; margin-left: auto; margin-right: auto;">


## 📦 数据集



## 🚀 快速开始

## 引用

如果您的研究工作使用或参考了 A.S.E 及其评测结果，请按照以下方式引用：
```bibtex
@misc{lian2025aserepositorylevelbenchmarkevaluating,
      title={A.S.E: A Repository-Level Benchmark for Evaluating Security in AI-Generated Code}, 
      author={Keke Lian and Bin Wang and Lei Zhang and Libo Chen and Junjie Wang and Ziming Zhao and Yujiu Yang and Miaoqian Lin and Haotong Duan and Haoran Zhao and Shuang Liao and Mingda Guo and Jiazheng Quan and Yilu Zhong and Chenhao He and Zichuan Chen and Jie Wu and Haoling Li and Zhaoxuan Li and Jiongchi Yu and Hui Li and Dong Zhang},
      year={2025},
      eprint={2508.18106},
      archivePrefix={arXiv},
      primaryClass={cs.SE},
      url={https://arxiv.org/abs/2508.18106}, 
}
```

## 共建指南



## ✨ 亮点设计

* **项目级代码生成场景**：基于真实世界 GitHub 项目，模拟 AI IDE 实际工作流程，在生成代码时，LLM 不仅需要理解代码功能描述，还需理解从项目中提取的代码上下文。
* **安全敏感场景设计**：任务设计源自真实 CVE 漏洞，由安全专家精选，聚焦安全关键的代码生成场景。
* **数据泄露风险缓解**：引入双重代码变异技术，对原始种子数据进行代码结构变异与代码语义变异，以缓解 LLM 训练过程中的数据泄露风险，保障评估的公正性。
* **专家级定制安全评估**：由安全专家为每个 CVE 定制专属漏洞检测规则，确保评估的准确性和针对性。
* **多语言支持**：A.S.E 1.0 包含 40 条高质量种子数据和 80条变异数据，涵盖了 4 种热门漏洞类型：跨站脚本攻击，SQL 注入，路径穿越，命令注入，涉及 Java，Python，Go，JavaScript 和 PHP 5 种主流编程语言。
* **多维度评估**：从代码安全性、质量、生成稳定性三方面对 LLM 生成代码能力进行综合评估，同时支持漏洞类型等专项分析。



## 🚀 使用 A.S.E

### 运行环境配置

* 硬件要求：可用磁盘空间 50GB 及以上，内存推荐 16GB 及以上

* Python 版本: 3.11 或更高

  ```
  # 安装依赖
  pip install -r requirements.txt
  ```

* 安装 [docker](https://docs.docker.com/engine/install/)  
  ```
  # 执行如下命令，测试 docker 环境可用性
  docker pull aiseceval/ai_gen_code:latest
  ```


### 运行示例

```
python invoke.py \
  --model_name="待测试模型名称" \ 
  --batch_id="v1.0" \ 
  --base_url="https://xxx/" \
  --api_key="你的大模型API密钥" \
  --github_token="你的GitHub令牌"
```

| 参数名         | 是否必需 | 说明                       | 示例值                                 |
| -------------- | ------- | -------------------------- | -------------------------------------- |
| model_name     | 必需    | 大模型名称                 | gpt-4o-2024-11-20                      |
| batch_id       | 必需    | 测试批次ID                 | v1.0                                   |
| base_url       | 必需    | 大模型API服务地址          | https://api.openai.com/v1/       |
| api_key        | 必需    | 大模型API密钥              | sk-xxxxxx                              |
| github_token   | 必需    | GitHub访问令牌             | ghp_xxxxxxxx                           |
| output_dir     | 可选    | 输出目录                   | outputs (默认值)                              |
| temperature    | 可选    | 生成文本的随机性参数       | 0.2 (默认使用服务端默认配置)         |
| top_p          | 可选    | 生成文本的多样性参数       | 0.8 (默认使用服务端默认配置)         |
| max_context_token | 可选 | 提示词输入最大token数          | 64000 (默认值)                               |
| max_gen_token  | 可选    | 生成文本最大token数        | 64000 (默认值)                                |
| model_args     | 可选    | 模型参数（JSON格式字符串） | {"temperature": 0.2, "top_p": 0.8}    |
| max_workers    | 可选    | 最大并发数（SAST 扫描）   | 1 (默认值) |


测评结果输出文件：`{output_dir}/{model_name}__{batch_id}_eval_result.txt`

注：完整评估耗时较长，用户可通过根据实验设备硬件属性增加并发数提速。此外，工具已内置自动断点重连机制，用户中断代码后只需直接运行代码即可继续恢复执行。


### LLM 调用支持
本项目目前支持符合 OpenAI API 标准的 LLM 服务。如需使用其他定制化的 LLM 调用方式，可修改 `bench/generate_code.py` 中的 `call_llm()` 函数来实现自定义调用逻辑。


<!-- ### 加入排行榜
如果您有兴趣将您的模型评测结果提交到我们的官网，请按照 [TencentAISec/experiments](https://github.com/TencentAISec/experiments/blob/main/README_zh.md) 中发布的指令操作。 -->








## 🙏 致谢
A.S.E​ 由腾讯安全平台部联合以下学术单位共同建设：
* ​复旦大学​（系统软件与安全实验室）
* 北京大学​（李挥教授团队）
* 上海交通大学​（网络与系统安全研究所）
* 清华大学​（杨余久教授团队）
* 浙江大学​（赵子鸣研究员团队）

感谢各方对 A.S.E 的卓越贡献。



## 加入社区

<img src="./img/wechat.jpg">

## 📄 开源协议
本项目基于 Apache-2.0 许可证开源，详细信息请查阅 [License.txt](./License.txt) 文件。


---

[![Star History Chart](https://api.star-history.com/svg?repos=Tencent/AICGSecEval&type=Date)](https://www.star-history.com/#Tencent/AICGSecEval&Date)