#!/usr/bin/env python3
"""白泽 System One 旁路门控 5 大维度基准压测与对抗复现脚本 (PR #10 / Issue #11)。

覆盖 5 大维度 20 个高难度真实样本：
1. 纯闲聊/日常/情绪发泄 (期望: 拦截 / 0)
2. 核心事实/网络/生辰八字 (期望: 入库 / 1)
3. 混合句（一半水话，夹带私货/核心配置）(期望: 提炼入库 / 1)
4. 否定/纠偏/旧账作废 (期望: 提炼入库 / 1)
5. 长文本/中英黑话/多复合指令 (期望: 抗噪入库 / 1)

用法：
  python scripts/benchmark_gates.py [--url URL] [--key KEY] [--model MODEL]
"""

import argparse
import json
import os
import statistics
import time
import urllib.request

BENCHMARK_CASES = [
    # 维度一：纯闲聊/日常/发泄 (期望: 拦截 / False)
    ("E1_闲聊日常", "今天中午在公司食堂吃了个牛肉面，味道还行就是牛肉给太少了", False, "ephemeral"),
    ("E2_情绪吐槽", "今天这破天气一直下雨，烦死了，下班都没法骑电动车回家", False, "ephemeral"),
    ("E3_临时任务", "把当前目录下的 log 归档一下，顺便看一下剩余磁盘还有多少G", False, "ephemeral"),
    ("E4_问候试探", "在吗？测试一下网络通不通，听到请回答", False, "ephemeral"),

    # 维度二：核心事实/网络/身份 (期望: 入库 / True)
    ("F1_网络IP", "家里的飞牛NAS换成了静态IP 192.168.31.235，网关指到主路由", True, "infra"),
    ("F2_生辰传统", "我生辰是96年腊月初七，回头算八字命盘别排错了", True, "identity"),
    ("F3_账号密码", "AList管理员账号是admin，密码是TIANXT97（大写），端口5244", True, "infra"),
    ("F4_资产持仓", "我的基金持仓目前只留半导体014320德邦、电力和信息科技，只减不追", True, "preference"),

    # 维度三：混合句（一半水话，夹带私货/核心事实） (期望: 入库 / True)
    ("M1_闲聊夹带NAS", "刚跟朋友喝完酒回家，头疼得要命，对了顺手把NAS的Samba端口改成了445", True, "infra"),
    ("M2_吐槽夹带偏好", "现在有些前端界面丑出天际，出图排版千万别用土味黑底，我极度反感那种压抑风格", True, "preference"),
    ("M3_琐事夹带工位", "今天工位空调冻死个人，另外我的工位PC主机名是DESKTOP-DTE8QPT，记住别弄混", True, "infra"),
    ("M4_长文假闲聊", "今天模具车间忙飞了，注塑件缩水率一直调不平。以后叫我老板就行，别再用小布那个旧称呼了", True, "identity"),

    # 维度四：否定/纠偏/旧账作废 (期望: 入库 / True)
    ("N1_旧IP废除", "不要再连以前那个10.0.0.1的旧测试网了，路由器早扔了，彻底废弃", True, "infra"),
    ("N2_禁令规则", "飞书发文件走lark-cli云文档，严禁裸发MEDIA:；架构图用SVG渲PNG直发，严禁ASCII画", True, "infra"),
    ("N3_行为纠偏", "系统逻辑类问题现场实测再张嘴，搜得到的别来问我，现场实弹验证", True, "preference"),
    ("N4_模型封杀", "播放器主力用OK影视和FongMi，绝对禁止推VidHub和Nova这种流氓软件", True, "preference"),

    # 维度五：长文本/中英黑话/复合逻辑 (期望: 入库 / True)
    ("L1_架构专线", "Google全家桶锁东京AWS专线严禁漏进三毛；custom_rules锚点必须置于geolocation-!cn前；NAS宿主sudo密码是bzssn1997，echo密码加sudo直通", True, "infra"),
    ("L2_影社播放排障", "影社资源存网盘Alist挂载直解0本地占用；排障必须先查watch_history与codec_tag_string，若报错优先检查Range标头与Content-Disposition", True, "infra"),
    ("L3_模具研发工程", "我是做电脑模具研发的，平常结构干涉和出模斜度扣得很死，你回答问题务必客观严谨，拒绝无脑迎合与虚假全绿", True, "identity"),
    ("L4_多指令长句", "10router升级老规矩：先让会话切内置mimo防掐断；升级完核查providerConnections表；白泽记忆门控务必Fail-open", True, "infra")
]

PROMPT_INSTRUCTIONS = (
    "这段文本是否包含需要永久记住的用户个人档案、硬件配置、网络拓扑、行为铁律或长期偏好？"
    "重要事实、配置规则、否定修正、个人背景或长期要求答 1；纯日常闲聊、吐槽发泄或一次性临时杂务答 0。"
)

CATEGORY_CRITERIA = {
    "identity": "用户画像、职业背景、生辰八字、称谓或身份事实",
    "infra": "NAS、网络IP、服务器、端口、脚本、硬件或IT配置",
    "preference": "用户审美、行为铁律、做事规范、黑名单或长期偏好",
    "ephemeral": "日常口水、纯情绪吐槽、临时指令或一次性琐事"
}


def run_benchmark(api_url: str, api_key: str, model: str, proxy: str | None = None):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler()
    )

    print(f"==================================================")
    print(f"🚀 开始 System One 基准压测: {model} @ {api_url}")
    print(f"==================================================")

    results = []
    latencies = []

    for idx, (t_id, text, expected_mem, exp_cat) in enumerate(BENCHMARK_CASES, start=1):
        payload = {
            "model": model,
            "state": text,
            "questions": {
                "should_memorize": {"type": "noul", "instructions": PROMPT_INSTRUCTIONS},
                "category": {"type": "choice", "criteria": CATEGORY_CRITERIA}
            }
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Baize/Gate-Benchmark (TypeSafe-Client)"
            },
            method="POST"
        )
        t0 = time.time()
        try:
            with opener.open(req, timeout=10) as resp:
                dur = round((time.time() - t0) * 1000, 1)
                latencies.append(dur)
                body = json.loads(resp.read().decode())
                ans = body.get("answers", {})
                noul = float(ans.get("should_memorize", {}).get("noul", -1))
                cat = str(ans.get("category", {}).get("choice", "unknown"))
                
                # 判定规则：noul >= 0.25 或 category != 'ephemeral' 则判定为保留入库
                decision_is_mem = not (noul < 0.25 and cat == "ephemeral")
                correct = (decision_is_mem == expected_mem)
                
                status_icon = "🟢" if correct else "🔴"
                print(f"[{idx:02d}/20] {status_icon} {t_id:15} | 耗时: {dur:6.1f}ms | noul: {noul:.4f} | cat: {cat:10} | 判定: {'保留' if decision_is_mem else '拦截'}")
                results.append({"id": t_id, "correct": correct, "noul": noul, "cat": cat, "lat": dur})
        except Exception as e:
            print(f"[{idx:02d}/20] ❌ {t_id:15} | 请求失败: {e}")
            results.append({"id": t_id, "correct": False, "error": str(e)})

    total_correct = sum(1 for r in results if r.get("correct"))
    acc = total_correct / len(results) * 100
    p50 = statistics.median(latencies) if latencies else 0
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

    print(f"\n==================================================")
    print(f"📊 基准压测报告汇总:")
    print(f"  - 总样本数: {len(results)}")
    print(f"  - 正确命中: {total_correct} / {len(results)}")
    print(f"  - 综合准确率: {acc:.1f}%")
    print(f"  - P50 延迟: {p50:.1f}ms")
    print(f"  - P95 延迟: {p95:.1f}ms")
    print(f"==================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="白泽门控基准压测")
    parser.add_argument("--url", default="https://api.codiv.ai/v1/systemone", help="API 端点")
    parser.add_argument("--key", default=os.getenv("CODIV_API_KEY", "sk-codiv-7R3oc00a6RylyqaEZgYVoJqYPRPw6puv1i9CYujD"), help="API 密钥")
    parser.add_argument("--model", default="openjev-latest", help="模型名称")
    parser.add_argument("--proxy", default="http://192.168.31.235:7890", help="HTTP 代理")
    args = parser.parse_args()

    run_benchmark(args.url, args.key, args.model, args.proxy)
