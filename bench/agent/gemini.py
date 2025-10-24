import argparse
import os
import subprocess
import time
from bench.agent.base import AgentBenchBase


class GeminiAgentBench(AgentBenchBase):
    def __init__(self, logger, repo_dir, agent_args):
        super().__init__(logger, repo_dir, agent_args)
        self._api_key = agent_args.gemini_api_key
        self._model_name = agent_args.gemini_model
        self._no_sandbox = agent_args.gemini_no_sandbox

    @staticmethod
    def parse_args(args):
        parser = argparse.ArgumentParser(
            description='配置 Gemini 用于 Agent 评测',
            usage="...other_args... --agent --agent_name gemini " +
                  "[--gemini_api_key <API_KEY> --gemini_model <MODEL> --gemini_no_sandbox]",
            add_help=False
        )
        parser.add_argument("--gemini_api_key", type=str,
                            help="API密钥，如果不提供则从环境变量GEMINI_API_KEY获取")
        parser.add_argument("--gemini_model", type=str,
                            default=None, help="模型名称")
        parser.add_argument("--gemini_no_sandbox",
                            default=False, action="store_true", help="是否关闭沙箱")
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

        args = ["gemini", "-d", "--yolo"]

        if self._api_key is not None:
            os.environ["GEMINI_API_KEY"] = self._api_key
        if not self._no_sandbox:
            os.environ["SANDBOX_SET_UID_GID"] = "true"
            args.append("--sandbox")
        if self._model_name is not None:
            args.extend(["-m", self._model_name])

        args.extend(["-p", prompt])

        self.logger.info(f"Gemini run command: {args[0:-1]} ...prompt...")

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
                        f"Gemini output: {stdout.decode().strip()}")
                while True:
                    stderr = process.stderr.read()
                    if not stderr:
                        break
                    self.logger.info(
                        f"Gemini output error: {stderr.decode().strip()}")
                time.sleep(0.1)

            exitcode = process.returncode

            self.logger.info(f"Gemini run finish, exitcode: {exitcode}")
            return exitcode == 0

        except Exception as e:
            self.logger.error(f"Gemini run error: {e}")
            return False
