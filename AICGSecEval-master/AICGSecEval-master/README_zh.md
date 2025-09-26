# A.S.E (AI Code Generation Security Evaluation)

腾讯安全平台部悟空代码安全团队推出的业内首个项目级 AI 生成代码安全性评测框架。

当前版本: 1.0

**用户反馈问卷**：https://doc.weixin.qq.com/forms/AJEAIQdfAAoARwAuganAD0CN2ZD20i6Sf
> 为了打造更加全面、可靠、科学的 AI 生成代码安全性评测基准，吸引更多用户共建，在此特别邀请您参与一个2分钟的用户需求调研，对于有价值的反馈我们后续将会安排寄送腾讯精美礼品，感谢大家的关注与支持。


## 目录

- [📖 项目概述](#-项目概述)
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



## 📖 项目概述

A.S.E (AI Code Generation Security Evaluation) 提供了一种全新的**项目级AI生成代码安全性**评测基准，旨在通过模拟真实世界AI编程过程，评估大语言模型（LLM）生成代码在安全性方面的表现。

不同于传统安全评测集所使用的片段级（函数或文件级）代码生成场景，A.S.E 借鉴行业前沿 [SWE-Bench](https://github.com/SWE-bench/SWE-bench) 代码生成方法，从真实世界 **GitHub 项目**中构建**项目级代码生成场景**，模拟 AI IDE（如 Cursor）在实际开发中结合项目上下文生成代码的工作模式。为了保证生成代码的安全敏感性，项目评测集源自安全专家精选的真实世界 **CVE 漏洞**，基于专家标注的关键漏洞代码设计代码生成任务。 

A.S.E 构建了多维度评估体系，全面检测 LLM 的代码生成能力：
* **代码安全性**：专家级定制检测，由安全专家为每个 CVE 定制专属漏洞检测规则，保障评估的准确性与针对性。
* **代码质量**：项目兼容性验证，生成代码需能够成功合入原项目并通过 SAST 工具的语法检查。
* **生成稳定性**：多轮输出一致性测试，每条测试数据会在相同输入条件下生成三轮结果进行对比分析。


> 🏆 [榜单传送门](https://aicgseceval.tencent.com/rank)

<img src="./img/arch.svg" style="display: block; margin-left: auto; margin-right: auto;">



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


### 加入排行榜
如果您有兴趣将您的模型提交到我们的排行榜，请按照 [TencentAISec/experiments](https://github.com/TencentAISec/experiments/blob/main/README_zh.md) 中发布的指令操作。



## 💭 未来计划

我们将持续优化和提升项目功能，未来的优化规划包括但不限于以下内容，欢迎大家积极讨论和提出建议。
* 数据集扩充：支持更多的漏洞类型（例如 OWASP Top 10），开发语言和应用场景。
* 数据集分级：引入科学的分类方法对数据集进行层次化分级。
* 评测方案优化：
  * 引入更先进的代码上下文提取算法（当前使用的算法：BM25）。
  * 引入基于动态 PoC 验证的安全评估方案，以提高评估准确性。
* 榜单优化：支持更多维度和粒度的模型能力对比。


## 🤝 贡献
我们诚挚欢迎社区的建议与贡献！
* 报告问题/提出建议: [提交 Issue](https://github.com/Tencent/AICGSecEval/issues)
* 提交代码/数据：[发起 Pull Request](https://github.com/Tencent/AICGSecEval/pulls)

**微信群**

<img src="./img/wechat.jpg">


## 🙏 致谢
A.S.E​ 由腾讯安全平台部联合以下学术单位共同建设：
* ​复旦大学​（系统软件与安全实验室）
* 北京大学​（李挥教授团队）
* 上海交通大学​（网络与系统安全研究所）
* 清华大学​（杨余久教授团队）
* 浙江大学​（赵子鸣研究员团队）

感谢各方对业界首个项目级AI生成代码安全性评测基准的卓越贡献。

​**✨ 诚邀共建**​

欢迎更多高校、研究机构与企业加入合作！请联系 security@tencent.com 或加入微信群。


### 贡献者
<div align="center">
     <a href="https://github.com/LianKee" style="text-align: center; margin: 0 10px;">
         <img src="https://avatars.githubusercontent.com/LianKee" width="50" height="50" style="border-radius: 50%; object-fit: cover;">
     </a>
     <a href="https://github.com/OpenWhitzard" style="text-align: center; margin: 0 10px;">
         <img src="https://avatars.githubusercontent.com/OpenWhitzard" width="50" height="50" style="border-radius: 50%; object-fit: cover;">
     </a>
     <a href="https://github.com/TheBinKing" style="text-align: center; margin: 0 10px;">
         <img src="https://avatars.githubusercontent.com/TheBinKing" width="50" height="50" style="border-radius: 50%; object-fit: cover;">
     </a>
     <a href="https://github.com/jzquan" style="text-align: center; margin: 0 10px;">
         <img src="https://avatars.githubusercontent.com/jzquan" width="50" height="50" style="border-radius: 50%; object-fit: cover;">
     </a>
     <a href="https://github.com/YilZhong" style="text-align: center; margin: 0 10px;">
         <img src="https://avatars.githubusercontent.com/YilZhong" width="50" height="50" style="border-radius: 50%; object-fit: cover;">
     </a>
</div>




## 📄 许可证
本项目基于 Apache-2.0 许可证开源，详细信息请查阅 [License.txt](./License.txt) 文件。



---

[![Star History Chart](https://api.star-history.com/svg?repos=Tencent/AICGSecEval&type=Date)](https://www.star-history.com/#Tencent/AICGSecEval&Date)