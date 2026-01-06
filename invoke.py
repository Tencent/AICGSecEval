import os
import time
import argparse
import asyncio

from bench.agent import agent_bench_map


async def invoke(args, remaining_args):
    batch_id = args.batch_id
    dataset_path = args.dataset_path
    retrieval_data_path = args.retrieval_data_path
    num_cycles = args.num_cycles
    output_dir = args.output_dir
    max_workers = args.max_workers
    run_step = args.run_step
    github_token = args.github_token

    start_time = time.time()
    # 创建输出目录
    raw_repo_dir = os.path.join(output_dir, "raw_repo")
    if not os.path.exists(raw_repo_dir):
        os.makedirs(raw_repo_dir)
    generated_code_dir = os.path.join(output_dir, "generated_code")
    if not os.path.exists(generated_code_dir):
        os.makedirs(generated_code_dir)

    if args.llm:
        llm_name = args.model_name
    elif args.agent:
        llm_name = args.agent_name

    # 生成代码
    if run_step in ['all', 'gen_code']:
        if args.llm:  
            from run_code_generation_llm import gen_code as gen_code_llm

            model_name = args.model_name
            base_url = args.base_url
            api_key = args.api_key
            max_context_token = args.max_context_token
            max_gen_token = args.max_gen_token

            if api_key is None:
                api_key_from_env = os.getenv('LLM_API_KEY')
                if type(api_key_from_env) == tuple:
                    api_key = api_key_from_env[0]

            if not hasattr(args, "model_args") or args.model_args is None:
                args.model_args = {}

            if hasattr(args, "temperature") and args.temperature is not None:
                args.model_args['temperature'] = args.temperature
            if hasattr(args, "top_p") and args.top_p is not None:
                args.model_args['top_p'] = args.top_p
            model_args = args.model_args
            
            gen_code_llm(model_name, batch_id, base_url, api_key, max_context_token, max_gen_token, 
                    dataset_path, retrieval_data_path, raw_repo_dir, generated_code_dir, num_cycles, github_token, **model_args)

        elif args.agent:
            from run_code_generation_agent import gen_code as gen_code_agent

            agent_name = args.agent_name
            sleep_time = args.sleep_time
            agent_class = agent_bench_map[agent_name]

            try:
                agent_args = agent_class.parse_args(remaining_args)
            except Exception as e:
                print(f"Agent ({agent_name}) 配置解析失败: {e}")
                exit(0)

            await gen_code_agent(agent_name, agent_class, agent_args, batch_id, dataset_path, retrieval_data_path, raw_repo_dir, generated_code_dir, num_cycles, github_token, sleep_time)

    gen_time = time.time()
    print(f"{llm_name} 生成代码耗时: {gen_time - start_time} 秒")

    if run_step in ['all', 'security_scan']:
        from run_evaluate import evaluate_score, print_detail_result
        from run_security_scan import security_scan

        # 评估代码安全性
        security_scan(generated_code_dir, llm_name, batch_id, dataset_path, max_workers)
        sc_time = time.time()
        print(f"{llm_name} 安全扫描耗时: {sc_time - gen_time} 秒")

        # 评估分数
        res = evaluate_score(generated_code_dir, llm_name, batch_id, dataset_path, num_cycles)
        # print_detail_result(output_dir, llm_name, batch_id, res)

    end_time = time.time()
    print(f"{llm_name} 总耗时: {end_time - start_time} 秒")


def parse_args():
    filename = os.path.basename(__file__)

    parser = argparse.ArgumentParser(
        description='调用大语言模型进行代码生成',
        usage=filename+' [-h] [options...] {--llm | --agent} [llm_options... | agent_options...]',
        add_help=False
    )

    help_group = parser.add_argument_group('帮助选项')
    help_group.add_argument('-h', '--help', action='help', help='显示帮助')

    common_group = parser.add_argument_group('通用选项')
    common_group.add_argument('--batch_id', type=str, required=True, help='测试批次ID')
    common_group.add_argument('--output_dir', type=str, default="outputs", help='输出目录（默认值：outputs）')
    common_group.add_argument('--max_workers', type=int, default=1, help='安全评估最大并发数（可根据硬件条件设置，默认值：1）')
    common_group.add_argument('--run_step', type=str, default='all', choices=['all', 'gen_code', 'security_scan'], help='执行步骤')
    common_group.add_argument('--dataset_path', type=str, default="data/data_v2.json", help='数据集路径')
    common_group.add_argument('--retrieval_data_path', type=str, default="data/data_v2_context_bm25.json", help='上下文检索数据路径（默认值：data/data_v2_context_bm25.json）')
    common_group.add_argument('--num_cycles', type=int, default=3, help='单条数据测试轮数（默认值：3）')
    common_group.add_argument('--github_token', type=str, default=None, help='GitHub Token，如果不提供则使用匿名克隆,可能存在克隆限频问题')

    codegen_mode_group = parser.add_argument_group('代码生成模式选项')
    codegen_mode_exclusive_group = codegen_mode_group.add_mutually_exclusive_group(required=True)
    codegen_mode_exclusive_group.add_argument('--llm', action='store_true', help='使用LLM模式进行代码生成')
    codegen_mode_exclusive_group.add_argument('--agent', action='store_true', help='使用Agent模式进行代码生成')

    codegen_llm_group = parser.add_argument_group('LLM模式代码生成（指定 --llm 时）选项')
    codegen_llm_group.add_argument('--model_name', type=str, help='要使用的模型名称，与使用的模型服务平台一致')
    codegen_llm_group.add_argument('--base_url', type=str, default="https://gnomic.nengyongai.cn/v1/", help='API服务URL')
    codegen_llm_group.add_argument('--api_key', type=str, help='API密钥，如果不提供则从环境变量LLM_API_KEY获取')
    codegen_llm_group.add_argument('--temperature', type=float, help='生成文本的随机性参数,默认使用服务端默认配置')
    codegen_llm_group.add_argument('--top_p', type=float, help='生成文本的多样性参数,默认使用服务端默认配置')
    codegen_llm_group.add_argument('--max_context_token', type=int, default=64000, help='输入提示词最大token数,默认64000')
    codegen_llm_group.add_argument('--max_gen_token', type=int, default=64000, help='输出文本最大token数,默认64000')

    codegen_agent_group = parser.add_argument_group('Agent模式代码生成（指定 --agent 时）选项')
    codegen_agent_group.add_argument('--agent_name', type=str, choices=list(agent_bench_map.keys()), help='Agent名称')
    codegen_agent_group.add_argument('--sleep_time', type=int, default=0, help='每个生成任务之间的睡眠时间，单位秒')

    args, remaining_args = parser.parse_known_args()

    if args.llm:
        if args.model_name is None:
            parser.error('代码生成使用LLM模式时，必须指定模型名称（--model_name）')
        if len(remaining_args) > 0:
            parser.error(f"代码生成使用LLM模式时，不支持额外参数：{remaining_args}")
    elif args.agent:
        if args.agent_name is None:
            parser.error("代码生成使用Agent模式时，必须指定Agent名称（--agent_name）")

    return args, remaining_args


if __name__ == "__main__":
    args, remaining_args = parse_args()

    print(f"使用数据集: {args.dataset_path}")
    print(f"使用检索数据: {args.retrieval_data_path}")
    print(f"生成循环次数: {args.num_cycles}")

    # 调用模型
    asyncio.run(invoke(args, remaining_args))

