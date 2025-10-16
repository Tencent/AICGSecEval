# Agent 代码生成模式共建指导

评测框架 2.0 代码生成模块，在原有支持 LLM 评测基础上，增加对 Agent 评测支持。

本文档主要介绍：如何调用 Agent 评测模式，如何开发 Agent 评测模块以支持不同的 Agent。通过本文档，社区贡献者可以快速上手并参与共建。

## 调用 Agent 评测模式

启动评测的命令行参数分为几个部分：
```
python3 invoke.py [评测框架通用选项] [指定代码生成模式] [LLM模式或Agent模式选项]
```

**评测框架通用选项：** 包括批次（必填）、GitHub Token、输入输出路径、执行步骤、循环次数等与代码生成无关的选项。

**指定代码生成模式：** 使用 `--llm` 或 `--agent` 指定评测 LLM 或评测 Agent。

**LLM 模式或 Agent 模式选项：** 指定的代码生成模式专有选项，如 LLM 模式需设置模型名称，Agent 模式需设置 Agent 名称等。

例如，在进行 LLM 评测时，可以使用以下方式启动：

```
python3 invoke.py \
  --batch_id BATCH_ID \
  --llm \
  --model_name MODEL_NAME
```

再例如，在进行 Agent 评测时，可以使用以下方式启动：
```
python3 invoke.py \
  --batch_id BATCH_ID \
  --agent \
  --agent_name AGENT_NAME \
  other_agent_options...
```

在启动 Agent 评测时，考虑到不同 Agent 可能会有不同的配置参数（如模型、权限、API 等），启动器会将所有未知参数（即不在 `-h` 帮助信息列出的选项）提交给对应的 Agent 评测模块进行解析，以实现对 Agent 配置参数的扩展。

例如，对 Claude Code 进行评测时，可以使用以下方式启动：
```
python3 invoke.py \
  --batch_id BATCH_ID \
  --agent \
  --agent_name claude_code \
  --claude_api_url https://ai.nengyongai.cn \
  --claude_api_key sk-XXXXX \
  --claude_model claude-sonnet-4-20250514
```

其中 `--claude_XXX` 几个选项由 Agent 评测模块解析使用。

## 开发 Agent 评测模块

Agent 评测模块需要实现对 Agent SDK 的调用，包括启动、停止、交互，并实现代码生成的交互、编写相应的 Prompt（Prompt 可复用已有 Agent 模块）。

开发一个 Agent 评测模块步骤：

1. 在 `bench/agent` 目录下新建一个 Python 文件，例如 `claude_code.py`

2. 按照以下框架编写代码：
```python
import argparse                                # 用于实现启动命令解析
import os
from bench.agent.base import AgentBenchBase    # Agent 评测模块必须继承 AgentBenchBase 类
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions    # 导入所需的 SDK

# 实现一个评测类，必须继承自 AgentBenchBase
class ClaudeCodeAgentBench(AgentBenchBase):
    def __init__(self, logger, repo_dir, agent_args):
        super().__init__(logger, repo_dir, agent_args)
        # 构造方法里可以做一些初始化的工作，但不建议在此启动 SDK
        self._api_url = agent_args.claude_api_url
        self._api_key = agent_args.claude_api_key
        self._model_name = agent_args.claude_model

    @staticmethod
    def parse_args(args):
        # 这里可以实现一个命令行 Parser
        # 函数的返回值会传入 __init__ 构造方法的 agent_args 参数
        parser = argparse.ArgumentParser(
            description='配置 Claude Code SDK 用于 Agent 评测',
            usage="...other_args... --agent --agent_name claude_code [--claude_api_url <API_URL> --claude_api_key <API_KEY> --claude_model <MODEL>]",
            add_help=False
        )
        parser.add_argument("--claude_api_url", type=str,
                            help="API服务URL，如果不提供则从环境变量ANTHROPIC_BASE_URL获取")
        parser.add_argument("--claude_api_key", type=str,
                            help="API密钥，如果不提供则从环境变量ANTHROPIC_AUTH_TOKEN获取")
        parser.add_argument("--claude_model", type=str,
                            default="claude-sonnet-4-20250514", help="模型名称")
        return parser.parse_args(args)

    # 这里启动 SDK
    async def start(self):
        if self._api_url is not None:
            os.environ["ANTHROPIC_BASE_URL"] = self._api_url
        if self._api_key is not None:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = self._api_key

        options = ClaudeCodeOptions(
            system_prompt="你是一个代码分析专家，分析完整项目中的代码并进行改写。",
            max_turns=None,
            allowed_tools=["Read", "Write", "Grep"],
            disallowed_tools=["Bash(rm*)"],
            model=self._model_name,
            cwd=self.repo_dir,        # 仓库根目录
            permission_mode="plan"
        )

        # 打印 log 时请使用 self.logger
        self.logger.info(f"Claude Code Agent is starting ...")
        self._agent = ClaudeSDKClient(options=options)
        await self._agent.connect()
        self.logger.info(f"Claude Code Agent has started")

    # 这里停止 SDK 并进行资源回收
    async def stop(self):
        self.logger.info(f"Claude Code Agent is stopping ...")
        await self._agent.disconnect()

    # 这里进行代码生成
    async def generate_code(self, file_path, function_summary, context_file_list):
        # 生成 Prompt，建议直接调用基类的 make_prompt()，如非特殊情况建议不要自行构造
        prompt = self.make_prompt(
            file_path, function_summary, context_file_list)
        self.logger.info(
            f"Claude Code Agent is generating code, prompt: {prompt}")

        # 需要自行实现 SDK 调用
        await self._agent.query(prompt)
        async for message in self._agent.receive_messages():
            if type(message).__name__ == "ResultMessage":
                break
            self.logger.info(f"Claude Code Agent response: {message}")

        # 返回是否调用成功
        return True
```

3. 将新建的 Agent 评测模块注册到 `bench/agent/__init__.py` 文件中
```python
from .claude_code import ClaudeCodeAgentBench    # 导入新建的模块

# 在这里注册所有可进行评测的 Agent：
#   key 为 Agent 的名称，对应到启动参数 --agent_name
#   value 为实现类，需要继承自 AgentBenchBase
agent_bench_map = {
    "claude_code": ClaudeCodeAgentBench,
    # 此处新增一项
}
```

4. 现在，可以使用以下启动参数进行测试：
```
python3 invoke.py \
    --batch_id BATCH_ID \
    --agent \
    --agent_name {你在__init__.py里注册的名称} \
    [...其他需要传给你编写的parse_args()函数的参数...]
```
