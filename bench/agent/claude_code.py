import argparse
import os
from bench.agent.base import AgentBenchBase
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions


class ClaudeCodeAgentBench(AgentBenchBase):
    def __init__(self, logger, repo_dir, agent_args):
        super().__init__(logger, repo_dir, agent_args)
        self._api_url = agent_args.claude_api_url
        self._api_key = agent_args.claude_api_key
        self._model_name = agent_args.claude_model

    @staticmethod
    def parse_args(args):
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
            cwd=self.repo_dir,
            permission_mode="plan"
        )

        self.logger.info(f"Claude Code Agent is starting ...")
        self._agent = ClaudeSDKClient(options=options)
        await self._agent.connect()
        self.logger.info(f"Claude Code Agent has started")

    async def stop(self):
        self.logger.info(f"Claude Code Agent is stopping ...")
        await self._agent.disconnect()

    async def generate_code(self, file_path, function_summary, context_file_list):
        prompt = self.make_prompt(
            file_path, function_summary, context_file_list)
        self.logger.info(
            f"Claude Code Agent is generating code, prompt: {prompt}")

        await self._agent.query(prompt)
        async for message in self._agent.receive_messages():
            if type(message).__name__ == "ResultMessage":
                break
            self.logger.info(f"Claude Code Agent response: {message}")

        return True
