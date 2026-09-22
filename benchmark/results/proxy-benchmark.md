# CjRepo Proxy Benchmark

> 实测时间：2026-09-22T19:15:53.7296170+08:00  
> 主机：WIN-1SO5CD96KP8；Microsoft Windows NT 10.0.26200.0；8 logical processors  
> 场景：本地 HTTP 请求一个包索引及 meshdep 2.0.0 制品。Cold 每轮清空服务端缓存；Warm 使用已校验缓存。

| 场景 | 轮次 | Median | P95 | Average | Min | Max |
|---|---:|---:|---:|---:|---:|---:|
| Cold / Cache MISS | 10 | 62.76 ms | 94.567 ms | 65.975 ms | 56.935 ms | 94.567 ms |
| Warm / Cache HIT | 50 | 33.102 ms | 42.805 ms | 34.003 ms | 26.235 ms | 48.852 ms |

Median speedup: **1.9x**

该结果衡量本机、无公网抖动条件下 CjRepo Proxy 自身的缓存路径差异，不代表官方中心仓的互联网延迟。原始样本保存在 proxy-benchmark.json，任何性能数字都可由 benchmark/proxy/run.ps1 重跑复验。
