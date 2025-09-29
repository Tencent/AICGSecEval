from .claude_code import ClaudeCodeAgentBench

# 在这里注册所有可进行评测的 Agent：
#   key 为 Agent 的名称，对应到启动参数 --agent_name
#   value 为实现类，需要继承自 AgentBenchBase
agent_bench_map = {
    "claude_code": ClaudeCodeAgentBench,
}

__all__ = ["agent_bench_map"]
