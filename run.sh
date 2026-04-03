#!/bin/bash
# Fund-Job Radar · 启动脚本
# 绝对路径：/home/xiaoduo/.openclaw/workspace-product/fund-job-radar/run.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
if [ -d ".venv/bin/python" ]; then
    source .venv/bin/activate
else
    echo "错误：未找到虚拟环境 .venv，请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

echo "============================================"
echo " Fund-Job Radar 启动中..."
echo " 数据目录: $SCRIPT_DIR/data"
echo " 配置文件: $SCRIPT_DIR/config.yaml"
echo "============================================"

# 运行主程序（APScheduler 调度）
python app/main.py
