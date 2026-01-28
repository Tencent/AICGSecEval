'''
给定数据集，执行 code indexing 和 code search，存储结果，用于后续多 LLM 批量测试。
'''

import os
import json
import argparse
from pathlib import Path

from bench import bm25_retrieval


def main(
    dataset_path: str,
    output_dir: str,
    github_token: str,
    base_url: str,
    openai_key: str,
    context_strategy: str = "file",
    procc_model: str = None,
    procc_window: int = 120,
    procc_max_gen_token: int = 256,
    procc_temperature: float = 0.2,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    dataset_name = os.path.basename(dataset_path)
    dataset_name = os.path.splitext(dataset_name)[0]
    print(f"处理数据集: {dataset_name}")

    instances = []
    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for instance in data:
            if "seed" not in instance or instance["seed"] == True:
                instances.append(instance)

    document_encoding_style = "file_name_and_contents"

    bm25_retrieval.main(
        dataset_name,
        instances,
        document_encoding_style,
        output_dir,
        False,
        github_token,
        base_url,
        openai_key,
        context_strategy=context_strategy,
        procc_model=procc_model,
        procc_window=procc_window,
        procc_max_gen_token=procc_max_gen_token,
        procc_temperature=procc_temperature,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='执行代码索引和搜索，存储结果用于后续测试')
    parser.add_argument('--input_file', type=str, default="data/data_v2.json", required=True, help='输入数据集文件路径')
    parser.add_argument('--output_dir', type=str, default='outputs/data_retrieval_bm25', help='输出结果目录')
    parser.add_argument('--github_token', type=str, default=None, help='GitHub Token（可选，不提供则匿名 clone 可能限频）')

    parser.add_argument('--base_url', type=str, default=None, help='API服务URL（默认取环境变量 LLM_BASE_URL）')
    parser.add_argument('--openai_key', type=str, default=None, help='API密钥（默认取环境变量 LLM_API_KEY）')

    parser.add_argument(
        '--context_strategy',
        type=str,
        default="file",
        choices=["file", "block", "procc"],
        help='上下文策略：file(默认) / block / procc(论文 completion/hypothetical-line)',
    )

    parser.add_argument('--procc_model', type=str, default=None, help='procc 使用的模型名（默认取环境变量 NENGYONGAI_MODEL）')
    parser.add_argument('--procc_window', type=int, default=120, help='prefix/suffix 行窗口大小（默认120行）')
    parser.add_argument('--procc_max_gen_token', type=int, default=256, help='hypothetical patch 最大生成 token（默认256）')
    parser.add_argument('--procc_temperature', type=float, default=0.2, help='hypothetical patch 生成温度（默认0.2）')

    args = parser.parse_args()

    base_url = args.base_url or os.getenv("LLM_BASE_URL") or "https://ai.nengyongai.cn/v1/"
    openai_key = args.openai_key or os.getenv("LLM_API_KEY")
    github_token = args.github_token or os.getenv("GITHUB_TOKEN")

    if openai_key is None:
        raise ValueError("openai_key 未提供：请设置 --openai_key 或环境变量 LLM_API_KEY")

    main(
        args.input_file,
        args.output_dir,
        github_token,
        base_url,
        openai_key,
        context_strategy=args.context_strategy,
        procc_model=args.procc_model,
        procc_window=args.procc_window,
        procc_max_gen_token=args.procc_max_gen_token,
        procc_temperature=args.procc_temperature,
    )
