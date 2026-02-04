# 📈 雪球组合调仓监控 (Xueqiu Rebalancing Monitor)

这是一个基于 **GitHub Actions + Python + Upstash Redis** 的轻量级 Serverless 监控系统。它能够定时抓取指定的雪球组合（Cube）调仓动态，并通过 **Bark** 实时推送到你的 iPhone。

## ✨ 主要功能

* **☁️ 云端运行**：依托 GitHub Actions 定时运行，无需购买服务器，零成本。
* **📱 实时推送**：发现调仓后立即通过 Bark 发送通知，包含具体的买卖操作和仓位变化（如：`买入 腾讯: 5% -> 6%`）。
* **💾 数据持久化**：使用 Upstash Redis 保存状态，防止重复推送。
* **📜 历史归档**：自动将详细的调仓记录（JSON + 总结文本）存入数据库，保留最新的 200 条记录，形成私人交易档案。
* **🚨 异常报警**：当雪球 Cookie 失效时，自动发送通知提醒更新。

## 🛠 技术架构

* **运行环境**: GitHub Actions (Ubuntu / Python 3.9)
* **数据库**: Upstash Redis (Serverless)
* **通知渠道**: Bark App (iOS)
* **依赖库**: `requests`

## 🚀 快速开始

### 1. 准备工作
* **GitHub 账号**：用于托管代码和运行 Action。
* **Bark App**：在 App Store 下载，获取你的推送 URL（例如 `https://api.day.app/你的Key/`）。
* **Upstash 账号**：注册 [Upstash](https://upstash.com/)，创建一个免费的 Redis 数据库，获取 `REST_URL` 和 `REST_TOKEN`。
* **雪球 Cookie**：登录雪球网页版，F12 打开开发者工具，刷新页面，在 Network 里找到任意请求，复制 `Cookie` 字符串。

### 2. 配置 GitHub Secrets
在你的 GitHub 仓库中，进入 **Settings** -> **Secrets and variables** -> **Actions**，点击 **New repository secret**，添加以下变量：

| Secret Name | 说明 | 示例值 |
| :--- | :--- | :--- |
| `BARK_KEY` | Bark 的推送链接 | `https://api.day.app/Cczzguh6xw.../` |
| `UPSTASH_REDIS_REST_URL` | Upstash 数据库地址 | `https://aws-us-east-1...upstash.io` |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash 访问令牌 | `AWOQASQgOW...=` |
| `XUEQIU_COOKIE` | 雪球网页版 Cookie | `xq_a_token=...; u=...;` |
| `XUEQIU_CUBES` | (推荐) JSON格式的组合列表 | `{"ZH123456":"组合名1 - 主理人", "ZH888888":"组合名2 - 主理人"}` |

### 3. 修改监控列表
**方式一 (推荐 - 安全)**：
在 GitHub Secrets 中添加 `XUEQIU_CUBES`，值为 JSON 格式的字典。这样你的关注列表不会暴露在代码中。
```json
{
  "ZH3126091": "狗不叫性乃遷 - 狗不叫/管我财",
  "ZH2269931": "靠价值赚钱吃海鲜 - 大黄蚬子hgx"
}
```

**方式二 (不推荐)**：
如果你不介意公开，也可以直接修改 `fetch_rebalancing.py` 中的 fallback 代码或者硬编码。

### 4. 运行频率配置
默认配置在 `.github/workflows/run.yml` 中：
* **常规检查**: 交易日每 20 分钟运行一次。
* **高频冲刺**: 交易日收盘前 15 分钟（A股 14:45+, 港股 15:45+），加密至 **每 5 分钟检查一次**，防止错过尾盘调仓。
* **周末休眠**: 每 6 小时运行一次（保活）。

---

## 📊 数据库结构 (Redis)

本系统在 Upstash 中维护两类数据：

### 1. 状态去重表 (Hash)
* **Key**: `xueqiu:status:last_ids`
* **作用**: 记录每个组合最后一次调仓的 ID，用于判断是否有新动态。
* **结构**: `{"ZH123456": "12345678", "ZH888888": "98765432"}`

### 2. 历史归档表 (List)
* **Key**: `xueqiu:history:ZHxxxxxx` (每个组合独立)
* **作用**: 存储详细的调仓历史 JSON 数据。
* **特性**: 自动修剪 (LTrim)，永远只保留最新的 **200** 条记录。
* **包含字段**: 
    * 原始调仓数据 (Snowball Raw Data)
    * `fetched_at`: 抓取时间
    * `summary_text`: 推送的文字总结 (如 "买入 腾讯: 5% -> 6%")

---

## 🔧 常见维护

### Cookie 失效怎么办？
如果手机收到“Cookie 失效”的报警：
1.  在电脑浏览器重新登录雪球，复制新的 Cookie。
2.  进入 GitHub 仓库 **Settings** -> **Secrets**。
3.  更新 `XUEQIU_COOKIE` 的值。
4.  **无需修改代码**，下次运行自动生效。

### 如何手动测试推送？
如果你想测试脚本是否正常工作，可以去 Upstash 控制台：
1.  找到 Key `xueqiu:status:last_ids`。
2.  删除其中一个组合的 ID 字段。
3.  在 GitHub Actions 页面点击 **Run workflow** 手动触发。
4.  脚本会认为那是“新调仓”并发送通知。

---

## ⚠️ 免责声明

本项目仅供技术学习和个人辅助使用。
* 投资有风险，抄作业需谨慎。
* 请合理设置运行频率，避免对雪球服务器造成压力。
* 数据来源于网络，不保证 100% 准确性或实时性。
