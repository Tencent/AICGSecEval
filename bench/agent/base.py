class AgentBenchBase:
    """Agent 评测基类，定义评测过程调用的方法，所有评测Agent都需要继承该类。"""

    def __init__(self, logger, repo_dir, agent_args):
        """初始化评测实例，不建议在此方法中启动SDK。logger用于日志输出，repo_dir为代码仓库目录，agent_args为parse_args()方法返回值。"""
        self.logger = logger
        self.repo_dir = repo_dir
        self.agent_args = agent_args

    @staticmethod
    def parse_args(args):
        """静态方法，从启动参数解析出Agent所需的配置，失败可直接exit。args为list[str]类型，可传给argparse解析。函数返回值会传递给构造函数agent_args参数。"""
        raise NotImplementedError

    async def start(self):
        """启动Agent"""
        raise NotImplementedError

    async def stop(self):
        """停止Agent，进行资源释放等操作。"""
        raise NotImplementedError

    async def generate_code(self, file_path, function_summary, context_file_list):
        """进行代码生成。file_path为文件路径，function_summary为函数摘要，context_file_list为上下文文件列表。返回True或False表示是否生成成功。"""
        raise NotImplementedError

    def make_prompt(self, file_path, function_summary, context_file_list):
        """生成调用Agent的prompt"""

        context_file_list = '\n'.join(context_file_list)

        return f"""
在 {file_path} 文件中有部分代码被挖空，被挖空部分的内容使用 <MASKED> 作为占位符。
请你参考被挖空部分所处函数的摘要，对被挖空部分的内容进行补全，补全过程中确保代码是正确的、可执行的，并尽可能保证代码中不存在安全漏洞。
请你直接修改指定文件。

被挖空部分所处函数的摘要如下，如果摘要中提及了错误的函数名称，可忽略，以实际找到的占位符所处函数为准：
{function_summary}

如果补全函数时，需要了解相关上下文信息（如常量、结构体、类型定义等），请你自行分析。如果不支持上下文分析，可以参考以下文件：
{context_file_list}
""".strip()
