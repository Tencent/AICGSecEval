'''
给定数据集，执行 code indexing 和 code search，存储结果，用于后续多 LLM 批量测试。
'''

import os
import json
import time
import argparse
from pathlib import Path

from bench import bm25_retrieval


def main(dataset_path,output_dir="data/tmp"):
      
    # 创建输出目录
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # 从文件路径中提取文件名作为数据集名称
    dataset_name = os.path.basename(dataset_path)
    # 如果需要去掉文件扩展名，可以使用以下代码
    dataset_name = os.path.splitext(dataset_name)[0]
    print(f"处理数据集: {dataset_name}")
    
    # 读取输入文件
    instances = []
    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for instance in data:
            if instance["seed"] == True:
                instances.append(instance)

    document_encoding_style = "file_name_and_contents"
    token = os.environ.get("GITHUB_TOKEN", "git")
    # 执行代码索引和搜索
    bm25_retrieval.main(dataset_name, instances, document_encoding_style, token, output_dir, False)



if __name__ == "__main__":
    # 解析命令行参数
    # parser = argparse.ArgumentParser(description='执行代码索引和搜索，存储结果用于后续测试')
    # parser.add_argument('--input_file', type=str, required=True, help='输入JSON文件路径')
    # parser.add_argument('--output_dir', type=str, default='results', help='输出结果目录')
    # args = parser.parse_args()
    # main(args.input_file, args.output_dir)

    # 标注的数据集
    dataset_path = "data/test.json"
    main(dataset_path)

