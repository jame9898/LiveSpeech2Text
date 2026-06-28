# -*- coding: utf-8 -*-
"""HF 版最小验证脚本：加载模型 + 流式转录测试。
验证三件事：
  1) Qwen3-ASR-*-hf 能否在 transformers 5.x 下加载
  2) GPU 推理是否正常
  3) transcribe_array 的 (ndarray, sr) 元组输入是否被 processor 接受（迁移风险点）
首次运行会从 hf-mirror 下载模型（1.7B 约 4.4GB）。
"""
import time
import traceback
import numpy as np
import core

print("=" * 60)
print("HF 版最小验证")
print("=" * 60)

t0 = time.time()
eng = core.ASREngine()
print(f"[1/4] 实例化 ASREngine ({time.time()-t0:.1f}s)")

# 优先 1.7B（已本地下载）；如要测 1.7B 改成 'qwen3-asr-1.7b'
print("[2/4] 加载模型 qwen3-asr-1.7b（首次需下载，请耐心等待进度条）...")
t1 = time.time()
ok = eng.load_model('qwen3-asr-1.7b')
print(f"      load_model 返回: {ok}，耗时 {time.time()-t1:.1f}s")
if not ok:
    print("!! 模型加载失败，见上方报错")
    raise SystemExit(1)
print(f"      model_name = {eng.model_name}")
print(f"      device = {eng.model.device}")

# 生成 3 秒测试音频（440Hz 正弦波，模拟一段语音输入）
print("[3/4] 生成测试音频（3秒 440Hz 正弦波）...")
sr = 16000
t = np.linspace(0, 3.0, int(sr * 3.0), endpoint=False)
audio = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
print(f"      audio shape={audio.shape} sr={sr}")

# 验证流式元组输入接口（迁移风险点）
print("[4/4] 调用 transcribe_array（验证元组输入接口）...")
t2 = time.time()
try:
    text = eng.transcribe_array(audio, sr)
    print(f"      成功！耗时 {time.time()-t2:.1f}s")
    print(f"      识别结果: '{text}'")
    print("(注：正弦波不是真实语音，结果为空或乱码属正常，关键是接口不报错)")
    print("=" * 60)
    print("全部验证通过")
    print("=" * 60)
except Exception as e:
    print(f"      失败: {e}")
    traceback.print_exc()
    print("=" * 60)
    print("流式元组接口报错 - 需要回退到临时 wav 文件方案")
    print("=" * 60)
