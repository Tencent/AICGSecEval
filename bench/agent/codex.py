import argparse
import os
import subprocess
import time
from bench.agent.base import AgentBenchBase


class CodexAgentBench(AgentBenchBase):
    def __init__(self, logger, repo_dir, agent_args):
        super().__init__(logger, repo_dir, agent_args)
        self._api_url = agent_args.codex_api_url
        self._api_key = agent_args.codex_api_key
        self._wire_api = agent_args.codex_wire_api
        self._model_name = agent_args.codex_model
        self._sandbox_mode = agent_args.codex_sandbox_mode

    @staticmethod
    def parse_args(args):
        parser = argparse.ArgumentParser(
            description='配置 Codex 用于 Agent 评测',
            usage="...other_args... --agent --agent_name codex " +
                  "[--codex_api_url <API_URL> --codex_api_key <API_KEY> --codex_wire_api <WIRE_API> " +
                  "--codex_model <MODEL> --codex_sandbox_mode <SANDBOX_MODE>]",
            add_help=False
        )
        parser.add_argument("--codex_api_url", type=str,
                            default=None, help="API服务URL")
        parser.add_argument("--codex_api_key", type=str,
                            help="API密钥，如果不提供则从环境变量OPENAPI_API_KEY获取")
        parser.add_argument("--codex_wire_api", type=str,
                            default="chat", help="API接口")
        parser.add_argument("--codex_model", type=str,
                            default=None, help="模型名称")
        parser.add_argument("--codex_sandbox_mode", type=str,
                            default="workspace-write", help="沙箱模式")
        return parser.parse_args(args)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def generate_code(self, file_path, function_summary, context_file_list):
        prompt = self.make_prompt(
            file_path, function_summary, context_file_list)
        self.logger.info(
            f"Codex is generating code, prompt: {prompt}")

        if self._api_key is not None:
            os.environ["OPENAI_API_KEY"] = self._api_key

        args = ["codex"]
        if self._api_url is not None:
            args.extend([
                "-c", "model_providers.codex.name=\"codex\"",
                "-c", f"model_providers.codex.base_url=\"{self._api_url}\"",
                "-c", f"model_providers.codex.wire_api=\"{self._wire_api}\"",
                "-c", f"model_providers.codex.env_key=\"OPENAI_API_KEY\"",
                "-c", "model_provider=\"codex\"",
            ])
        if self._model_name is not None:
            args.extend(["--model", self._model_name])
        args.extend(["exec", "--sandbox", self._sandbox_mode, prompt])

        self.logger.info(f"Codex run command: {args[0:-1]} ...prompt...")

        try:
            process = subprocess.Popen(
                args=args,
                cwd=self.repo_dir,
                stdin=None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)

            while process.poll() is None:
                while True:
                    stdout = process.stdout.read()
                    if not stdout:
                        break
                    self.logger.info(
                        f"Codex output: {stdout.decode().strip()}")
                while True:
                    stderr = process.stderr.read()
                    if not stderr:
                        break
                    self.logger.info(
                        f"Codex output error: {stderr.decode().strip()}")
                time.sleep(0.1)

            exitcode = process.returncode

            self.logger.info(f"Codex run finish, exitcode: {exitcode}")
            return exitcode == 0

        except Exception as e:
            self.logger.error(f"Codex run error: {e}")
            return False
