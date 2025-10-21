import argparse
import os
import subprocess
from bench.agent.base import AgentBenchBase


class GeminiAgentBench(AgentBenchBase):
    def __init__(self, logger, repo_dir, agent_args):
        super().__init__(logger, repo_dir, agent_args)
        self._api_key = agent_args.gemini_api_key
        self._model_name = agent_args.gemini_model

    @staticmethod
    def parse_args(args):
        parser = argparse.ArgumentParser(
            description='配置 Gemini 用于 Agent 评测',
            usage="...other_args... --agent --agent_name gemini [--gemini_api_key <API_KEY> --gemini_model <MODEL>]",
            add_help=False
        )
        parser.add_argument("--gemini_api_key", type=str,
                            help="API密钥，如果不提供则从环境变量GEMINI_API_KEY获取")
        parser.add_argument("--gemini_model", type=str,
                            default=None, help="模型名称")
        return parser.parse_args(args)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def generate_code(self, file_path, function_summary, context_file_list):
        prompt = self.make_prompt(
            file_path, function_summary, context_file_list)
        self.logger.info(
            f"Gemini is generating code, prompt: {prompt}")

        if self._api_key is not None:
            os.environ["GEMINI_API_KEY"] = self._api_key

        args = ["gemini", "--yolo", "-p", prompt]
        if self._model_name is not None:
            args.extend(["-m", self._model_name])

        output = None

        try:
            output = subprocess.run(
                args=args,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True
            )

            self.logger.info(f"Gemini output: {output.stdout}")
            return True

        except Exception as e:
            self.logger.error(f"Gemini error: {e}, output: {output}")
            return False
