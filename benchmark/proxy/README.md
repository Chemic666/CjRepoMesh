# Proxy benchmark

该基准使用本地模拟上游，对“索引 + 指定版本制品”的完整 HTTP 往返进行冷缓存与热缓存对比。它不访问互联网，也不会下载安装组件。

```powershell
.\benchmark\proxy\run.ps1
```

默认执行 10 次 Cold 和 50 次 Warm 测量，输出 Markdown 报告及包含全部原始样本的 JSON。该基准只用于衡量 CjRepo Proxy 自身缓存路径，不能代替真实公网或企业内网测试。
