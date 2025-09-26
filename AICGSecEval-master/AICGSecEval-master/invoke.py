import os
import time
import argparse

from run_code_generation import gen_code
from run_evaluate import evaluate_score, print_detail_result
from run_security_scan import security_scan


def invoke(model_name, batch_id, base_url, api_key, max_context_token, max_gen_token, github_token, 
           dataset_path, retrieval_data_path, num_cycles, output_dir, max_workers, **model_args):
    start_time = time.time()
    # 创建输出目录
    raw_repo_dir = os.path.join(output_dir, "raw_repo")
    if not os.path.exists(raw_repo_dir):
        os.makedirs(raw_repo_dir)
    generated_code_dir = os.path.join(output_dir, "generated_code")
    if not os.path.exists(generated_code_dir):
        os.makedirs(generated_code_dir)

    # 生成代码
    gen_code(model_name, batch_id, base_url, api_key, max_context_token, max_gen_token, github_token, 
             dataset_path, retrieval_data_path, raw_repo_dir, generated_code_dir, num_cycles, **model_args)
    gen_time = time.time()
    print(f"{model_name} 生成代码耗时: {gen_time - start_time} 秒")

    # 评估代码安全性
    security_scan(generated_code_dir, model_name, batch_id, dataset_path, max_workers)
    sc_time = time.time()
    print(f"{model_name} 安全扫描耗时: {sc_time - gen_time} 秒")

    # 评估分数
    res = evaluate_score(generated_code_dir, model_name, batch_id, dataset_path)
    print_detail_result(output_dir, model_name, batch_id, res)

    end_time = time.time()
    print(f"{model_name} 总耗时: {end_time - start_time} 秒")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='调用大语言模型进行代码生成')
    parser.add_argument('--model_name', type=str, help='要使用的模型名称，与使用的模型服务平台一致')
    parser.add_argument('--batch_id', type=str, help='测试批次ID')
    parser.add_argument('--base_url', type=str, default="https://gnomic.nengyongai.cn/v1/", help='API服务URL')
    parser.add_argument('--output_dir', type=str, default="outputs", help='输出目录')
    parser.add_argument('--api_key', type=str, help='API密钥，如果不提供则从环境变量LLM_API_KEY获取')
    parser.add_argument('--github_token', type=str, help='GitHub令牌，如果不提供则从环境变量GITHUB_TOKEN获取')
    parser.add_argument('--temperature', type=float, help='生成文本的随机性参数')
    parser.add_argument('--top_p', type=float, help='生成文本的多样性参数')
    parser.add_argument('--max_context_token', type=int, default=64000, help='提示词最大token数')
    parser.add_argument('--max_gen_token', type=int, default=64000, help='生成文本最大token数')
    parser.add_argument('--model_args', type=str, default="{}", help='模型参数')
    parser.add_argument('--max_workers', type=int, default=1, help='最大并发数（SAST扫描）')
    
    args = parser.parse_args()

    # 必要参数 model_name ,base_url, api_key, github_token
    if args.model_name is None:
        print("请提供模型名称")
        exit()
    if args.batch_id is None:
        print("请提供测试批次ID")
        exit()
    if args.base_url is None:
        print("请提供API服务URL")
        exit()
    if args.api_key is None:    
        print("请提供API密钥")
        exit()
    if args.github_token is None:
        print("请提供GitHub令牌")
        exit()

    model_args = {}
    if args.temperature is not None:
        model_args['temperature'] = args.temperature
    if args.top_p is not None:
        model_args['top_p'] = args.top_p

    if args.api_key is None:
        api_key = os.getenv('LLM_API_KEY')
        if type(api_key) == tuple:
            api_key = api_key[0]
        args.api_key = api_key
    
    if args.github_token is None:
        github_token = os.getenv('GITHUB_TOKEN')
        if type(github_token) == tuple:
            github_token = github_token[0]
        args.github_token = github_token

    # 预定义参数
    dataset_path = "data/data_v1.json"
    # dataset_path = "data/test.json"
    retrieval_data_path = "data/data_v1_retrieval_data.json"
    num_cycles = 3
    
    # 调用模型
    invoke(args.model_name, args.batch_id, args.base_url, args.api_key, args.max_context_token, args.max_gen_token,
           args.github_token, dataset_path, retrieval_data_path, num_cycles, args.output_dir, args.max_workers, 
           **model_args)


