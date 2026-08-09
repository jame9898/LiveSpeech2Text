# -*- coding: utf-8 -*-
"""自动测速选择最快 pip 镜像源并安装项目依赖。

用法:
    python install.py              # CPU 版依赖
    python install.py --gpu        # GPU + CUDA 版依赖
    python install.py --index-url https://pypi.tuna.tsinghua.edu.cn/simple   # 手动指定源
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

PYPI_SOURCES = {
    "官方 PyPI": "https://pypi.org/simple",
    "清华 TUNA": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "阿里云": "https://mirrors.aliyun.com/pypi/simple",
    "腾讯云": "https://mirrors.cloud.tencent.com/pypi/simple",
    "中科大 USTC": "https://pypi.mirrors.ustc.edu.cn/simple",
}

PYTORCH_SOURCES = {
    "PyTorch 官方": "https://download.pytorch.org/whl/cu126",
    "阿里云 PyTorch": "https://mirrors.aliyun.com/pytorch-wheels/cu126",
}

SPEEDTEST_PATH = "/torch/"
SAMPLE_SIZE = 65536
SPEEDTEST_TIMEOUT = 5.0
HEADERS = {"User-Agent": "Mozilla/5.0 (install.py)"}


def measure_speed(url, path, size):
    target = url.rstrip("/") + path
    req = urllib.request.Request(target, headers=HEADERS)
    t0 = time.time()
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=SPEEDTEST_TIMEOUT) as resp:
            while total < size:
                chunk = resp.read(8192)
                if not chunk:
                    break
                total += len(chunk)
    except Exception:
        return None
    dt = time.time() - t0
    if total <= 0 or dt <= 0:
        return None
    return total / dt


def pick_fastest(sources, path, size):
    results = []
    for name, url in sources.items():
        print(f"[测速] {name}: {url}", flush=True)
        speed = measure_speed(url, path, size)
        if speed is None:
            print("       -> 不可达/超时", flush=True)
        else:
            print(f"       -> {speed / 1024:.0f} KB/s", flush=True)
            results.append((speed, name, url))
    if not results:
        print("[错误] 所有镜像源均不可达，请检查网络后重试", flush=True)
        sys.exit(1)
    results.sort(key=lambda x: x[0], reverse=True)
    speed, name, url = results[0]
    print(f"[选择] 最快源: {name} ({speed / 1024:.0f} KB/s)", flush=True)
    return url


def build_gpu_requirements(src_extra_index_url):
    with open("requirements-gpu.txt", encoding="utf-8-sig") as f:
        content = f.read()
    pattern = re.compile(r"(?m)^--extra-index-url\s+\S+.*$")
    replaced = pattern.sub(f"--extra-index-url {src_extra_index_url}", content)
    if replaced == content:
        return "requirements-gpu.txt"
    fd, path = tempfile.mkstemp(prefix="l2t_req_gpu_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(replaced)
    return path


def main():
    parser = argparse.ArgumentParser(description="自动测速选择最快镜像源安装依赖")
    parser.add_argument("--gpu", action="store_true", help="安装 GPU + CUDA 版依赖")
    parser.add_argument("--index-url", help="手动指定 PyPI 镜像源，跳过 PyPI 测速")
    parser.add_argument("--pytorch-index-url", help="手动指定 PyTorch wheel 源，跳过 PyTorch 测速")
    parser.add_argument("--timeout", type=int, default=300, help="pip 下载超时秒数（默认 300）")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        print("[错误] 需要 Python 3.10+，当前版本:", sys.version.split()[0], flush=True)
        sys.exit(1)

    print("=" * 56, flush=True)
    print("  LiveSpeech2Text 依赖安装（自动选择最快镜像源）", flush=True)
    print("=" * 56, flush=True)

    pypi_url = args.index_url
    if not pypi_url:
        pypi_url = pick_fastest(PYPI_SOURCES, SPEEDTEST_PATH, SAMPLE_SIZE)

    req_file = "requirements-gpu.txt" if args.gpu else "requirements.txt"
    if not os.path.exists(req_file):
        print(f"[错误] 找不到 {req_file}，请在项目根目录运行", flush=True)
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "pip", "install",
        "-r", req_file,
        "-i", pypi_url,
        "--timeout", str(args.timeout),
    ]
    tmp_file = None
    if args.gpu:
        pt_url = args.pytorch_index_url
        if not pt_url:
            pt_url = pick_fastest(PYTORCH_SOURCES, SPEEDTEST_PATH, SAMPLE_SIZE)
        tmp_file = build_gpu_requirements(pt_url)
        cmd[cmd.index(req_file)] = tmp_file
        print(f"[配置] PyTorch 源: {pt_url}", flush=True)

    print(f"[执行] {' '.join(cmd)}", flush=True)
    ret = subprocess.call(cmd)
    if tmp_file and os.path.exists(tmp_file):
        try:
            os.remove(tmp_file)
        except OSError:
            pass
    if ret != 0:
        print("\n[提示] 安装中断（多为网络波动）。pip 已有缓存，直接重新运行本脚本即可续传。", flush=True)
    else:
        print("\n[完成] 依赖安装成功。启动: python app.py（或双击 start.bat）", flush=True)
    sys.exit(ret)


if __name__ == "__main__":
    main()
