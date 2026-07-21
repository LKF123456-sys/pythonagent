"""负载测试脚本（httpx + asyncio 实现，无需 locust）。

用法：
    python scripts/load_test.py --mode health -c 20 -n 200
    python scripts/load_test.py --mode me     -c 20 -n 200
    python scripts/load_test.py --mode chat   -c 5  -n 20

模式说明：
    health : GET  /api/health   无需认证，压测 Web 层基础吞吐
    me     : GET  /api/auth/me  JWT 认证 + 一次 DB 查询，轻量鉴权端点
    chat   : POST /api/chat     完整智能体管线（含 LLM 调用），慢且消耗 token，
             小并发少量请求即可，主要用于观察端到端延迟而非极限吞吐

注意：
    - 注册接口有限流（3/min），脚本每次运行仅注册一次并复用 token。
    - 测量极限吞吐时请先调高限流配置，否则大量 429 会拉高"错误率"。
    - 指标：成功/失败数、错误率、QPS、延迟 avg/p50/p95/p99/max。
"""

import argparse
import asyncio
import statistics
import time
import uuid
from collections import Counter

import httpx


async def _register(client: httpx.AsyncClient, base_url: str) -> str:
    """注册一个一次性测试用户并返回 access_token。"""
    username = f"load_{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        f"{base_url}/api/auth/register",
        json={"username": username, "password": "loadtest123"},
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"注册测试用户失败（{resp.status_code}: {resp.text}）。"
            f"可能触发注册限流，请稍后重试或改用 --mode health。"
        )
    return resp.json()["access_token"]


def _percentile(sorted_data: list, pct: float) -> float:
    """线性插值法计算百分位数（输入须已升序排序）。"""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return float(sorted_data[f])
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


async def _worker(
    worker_id: int,
    queue: asyncio.Queue,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    mode: str,
    results: list,
    errors: list,
) -> None:
    """工作协程：从队列取任务发请求，记录延迟（毫秒）。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        start = time.perf_counter()
        try:
            if mode == "health":
                resp = await client.get(f"{base_url}/api/health")
            elif mode == "me":
                resp = await client.get(f"{base_url}/api/auth/me", headers=headers)
            else:  # chat
                resp = await client.post(
                    f"{base_url}/api/chat",
                    json={"question": "你好，请用一句话介绍量子计算。"},
                    headers=headers,
                )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if resp.status_code < 400:
                results.append(elapsed_ms)
            else:
                errors.append((str(resp.status_code), elapsed_ms))
        except Exception as e:  # noqa: BLE001 - 压测需捕获一切失败
            errors.append((f"EXC:{type(e).__name__}", (time.perf_counter() - start) * 1000.0))
        finally:
            queue.task_done()


def _report(mode: str, concurrency: int, total: int, results: list, errors: list, wall: float) -> None:
    """打印压测报告。"""
    ok, fail = len(results), len(errors)
    print("\n" + "=" * 62)
    print(f"负载测试报告  mode={mode}  concurrency={concurrency}  total={total}")
    print("=" * 62)
    print(f"成功: {ok}   失败: {fail}   错误率: {fail / total * 100:.2f}%")
    print(f"总耗时: {wall:.2f}s   QPS: {total / wall:.2f}")
    if results:
        s = sorted(results)
        print(
            f"延迟(ms): avg={statistics.mean(s):.1f}  "
            f"p50={_percentile(s, 50):.1f}  p95={_percentile(s, 95):.1f}  "
            f"p99={_percentile(s, 99):.1f}  max={s[-1]:.1f}"
        )
    if errors:
        codes = Counter(code for code, _ in errors)
        print(f"错误分布: {dict(codes)}")
    print("=" * 62)


async def run_load_test(base_url: str, concurrency: int, total: int, mode: str, timeout: float) -> None:
    """执行负载测试主流程。"""
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = ""
        if mode in ("me", "chat"):
            token = await _register(client, base_url)
            print("已注册测试用户并获取 token")

        queue: asyncio.Queue = asyncio.Queue()
        for i in range(total):
            queue.put_nowait(i)

        results: list = []
        errors: list = []
        workers = [
            asyncio.create_task(
                _worker(i, queue, client, base_url, token, mode, results, errors)
            )
            for i in range(concurrency)
        ]
        t0 = time.perf_counter()
        await asyncio.gather(*workers)
        wall = time.perf_counter() - t0

        _report(mode, concurrency, total, results, errors, wall)


def main() -> None:
    parser = argparse.ArgumentParser(description="负载测试脚本（httpx + asyncio）")
    parser.add_argument("--base-url", default="http://localhost:8000", help="目标服务地址")
    parser.add_argument("--mode", choices=["health", "me", "chat"], default="health", help="压测端点")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="并发协程数")
    parser.add_argument("-n", "--requests", type=int, default=100, help="总请求数")
    parser.add_argument("--timeout", type=float, default=60.0, help="单请求超时（秒）")
    args = parser.parse_args()

    print(f"目标: {args.base_url}  模式: {args.mode}  并发: {args.concurrency}  总量: {args.requests}")
    asyncio.run(run_load_test(args.base_url, args.concurrency, args.requests, args.mode, args.timeout))


if __name__ == "__main__":
    main()
