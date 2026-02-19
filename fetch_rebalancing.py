import requests
import json
import os
import time
import sys

# --- 配置区域 ---
def load_cube_config():
    """从环境变量安全加载组合配置"""
    config_str = os.environ.get("XUEQIU_CUBES")
    if not config_str:
        print("⚠️ 警告：未检测到 XUEQIU_CUBES 环境变量，将无法监控任何组合")
        exit(1) # 强制阻断
    
    try:
        return json.loads(config_str)
    except json.JSONDecodeError:
        print("❌ 错误：XUEQIU_CUBES 格式无效，请检查是否为标准 JSON")
        exit(1) # 强制阻断

# --- 配置初始化 ---
CUBE_DICT = load_cube_config()

# 数据库存储 Key (状态表，仅存最新ID用于去重)
DB_KEY_STATUS = 'xueqiu:status:last_ids'

# 历史记录保留条数 (0-199 即保留 200 条)
HISTORY_LIMIT = 200

# Cookie 失效报警间隔 (3天)
COOKIE_ALERT_INTERVAL = 86400 

# --- 环境变量获取 ---
COOKIE_STR = os.environ.get("XUEQIU_COOKIE")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
# 假设 Secret 填的是完整链接: https://api.day.app/YourKey/
BARK_URL = os.environ.get("BARK_KEY") 

# --- 基础检查 ---
if not BARK_URL:
    print("错误：未检测到 BARK_KEY，请在 GitHub Settings -> Secrets 里配置！")
    exit(1)
if not UPSTASH_URL or not UPSTASH_TOKEN:
    print("错误：未检测到 Upstash 配置，请检查 Secrets！")
    exit(1)

# --- 请求头 (Cookie) ---
# 注意：如果 Cookie 过期，请更新这里
# --- 请求头 (Cookie) ---
# 全局 Session 对象
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://xueqiu.com/'
})

def send_bark(title, body, symbol=None):
    """发送 Bark 通知 (POST 方式 + 强制保存历史)"""
    payload = {
        'title': title,
        'body': body,
        'icon': 'https://xueqiu.com/favicon.ico',
        'group': '雪球调仓',
        'isArchive': 1, # 1=保存历史消息
    }
    if symbol:
        payload['url'] = f"https://xueqiu.com/P/{symbol}"
    
    try:
        # 处理 URL 末尾斜杠，防止拼接错误
        url = BARK_URL
        if not url.endswith('/'):
            url += '/'
        requests.post(url, data=payload, timeout=10)
        print(f"推送成功: {title}")
    except Exception as e:
        print(f"推送失败: {e}")

def get_data_from_db(key):
    """从 Upstash Redis 读取状态"""
    url = f"{UPSTASH_URL}/get/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers)
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
        return {}
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return {}

def save_data_to_db(key, data_dict):
    """保存状态到 Upstash Redis"""
    url = f"{UPSTASH_URL}/set/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    try:
        requests.post(url, headers=headers, data=json.dumps(data_dict))
    except Exception as e:
        print(f"数据库保存失败: {e}")

def get_cookies_from_db():
    """从 Redis 读取持久化的 Cookies"""
    key = "xueqiu:cookies"
    url = f"{UPSTASH_URL}/get/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers)
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
        return {}
    except Exception as e:
        print(f"Cookie 读取失败: {e}, 将使用默认配置")
        return {}

def save_cookies_to_db():
    """
    将 Session 中的 Cookies 保存到 Redis
    (仅保存动态更新的部分，排除敏感的基础 Token)
    """
    key = "xueqiu:cookies"
    cookies_dict = requests.utils.dict_from_cookiejar(SESSION.cookies)
    
    # --- 隐私过滤 ---
    # 我们只希望保存服务器动态更新的“风控/会话”Cookie
    # 不需要保存已在 Secrets 里的静态“登录”Cookie (如 xq_a_token, u)
    # 这样 Redis 里就不会存有你的核心登录凭证，只是一堆临时的令牌
    SENSITIVE_KEYS = ['xq_a_token', 'xqat', 'u', 'user_id', 'bid']
    filtered_cookies = {k: v for k, v in cookies_dict.items() if k not in SENSITIVE_KEYS}
    
    # 如果过滤后为空，就不存了
    if not filtered_cookies:
        return

    # 简单的脱敏日志
    # print(f"保存更新的 Cookies: {list(filtered_cookies.keys())}")
    
    url = f"{UPSTASH_URL}/set/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    try:
        requests.post(url, headers=headers, data=json.dumps(filtered_cookies))
    except Exception as e:
        print(f"Cookie 保存失败: {e}")

def log_history_to_db(symbol, trade_detail):
    """
    [核心逻辑] 将详细调仓历史存入 List，并维持长度在 200 条
    """
    key = f"xueqiu:history:{symbol}"
    
    # LPUSH: 从左侧(头部)插入新数据
    push_url = f"{UPSTASH_URL}/lpush/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    
    # 增加抓取时间戳
    trade_detail['fetched_at'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    
    try:
        # 1. 写入数据
        requests.post(push_url, headers=headers, data=json.dumps(trade_detail))
        
        # 2. 自动修剪 (LTRIM 0 199 表示保留前 200 个元素)
        trim_url = f"{UPSTASH_URL}/ltrim/{key}/0/{HISTORY_LIMIT - 1}"
        requests.post(trim_url, headers=headers)
        
        print(f"[{symbol}] 历史详情已归档 (保留最新{HISTORY_LIMIT}条)")
    except Exception as e:
        print(f"[{symbol}] 历史归档失败: {e}")

def check_cookie_status(status_code, saved_data):
    if status_code in [400, 401, 403]:
        print(f"❌ [Cookie检查] 请求被拒绝，HTTP状态码: {status_code}")
        last_alert = saved_data.get('last_cookie_alert_time', 0)
        now = time.time()
        if now - last_alert > COOKIE_ALERT_INTERVAL:
            print("⚠️ 触发 Cookie 失效报警...")
            send_bark("雪球监控警告", f"Cookie似乎失效了(HTTP {status_code})，请更新 Secrets")
            saved_data['last_cookie_alert_time'] = now
            return False
        else:
            print("ℹ️ 报警冷却中，跳过发送通知")
        return False
    return True

def monitor_one_cube(symbol, full_name, saved_data):
    url = f"https://xueqiu.com/cubes/rebalancing/history.json?cube_symbol={symbol}&count=1&page=1"
    try:
        # 使用全局 SESSION 发起请求，自动处理 Cookie
        resp = SESSION.get(url, timeout=10)
        
        if not check_cookie_status(resp.status_code, saved_data): 
            return False # Cookie 失效，返回 False
        
        if resp.status_code == 200:
            data = resp.json()
            if 'list' in data and len(data['list']) > 0:
                latest_trade = data['list'][0]
                current_id = str(latest_trade['id'])
                current_status = latest_trade.get('status', 'unknown')
                
                # --- [读] 读取上次状态 ---
                saved_record = saved_data.get(symbol, {})
                last_id = saved_record.get('id', "")
                last_status = saved_record.get('status', 'unknown')
                
                # --- [判] ID变动 或 状态变动 (仅当ID一致时才对比状态) ---
                is_new_trade = (current_id != last_id)
                is_status_update = (current_id == last_id and current_status != last_status)
                
                if is_new_trade or is_status_update:
                    print(f"[{full_name}] 发现更新: {current_id} ({current_status})")
                    
                    # --- 1. 统一处理标题和表头 ---
                    if " - " in full_name:
                        cube_name, manager = full_name.split(" - ", 1)
                        header_line = f"👤主理人: {manager}"
                    else:
                        cube_name = full_name
                        header_line = f"📦组合: {full_name}"
                    
                    # --- 状态判定 ---
                    category = latest_trade.get('category', 'unknown')
                    status = current_status # 使用已获取的变量
                    
                    if category == 'sys_rebalancing':
                        status_str = '⚙️[系统]'
                    elif category == 'user_rebalancing':
                        status_map = {'success': '✅[成功]', 'failed': '❌[失败]', 'pending': '⏳[待成交]'}
                        status_str = status_map.get(status, f'[{status}]')
                    else:
                        status_str = '❓[未知]'
                    
                    title = f"{status_str}调仓-{cube_name}"

                    # --- 解析调仓时间 (北京时间) ---
                    created_at = latest_trade.get('created_at')
                    if created_at:
                        # 毫秒转秒，并加8小时(28800秒)转为北京时间，防止GitHub服务器时区差异
                        struct_time = time.gmtime(created_at / 1000 + 28800)
                        time_str = time.strftime("%Y-%m-%d %H:%M:%S", struct_time)
                    else:
                        time_str = "未知"
                    
                    # --- 2. 构造消息行 ---
                    msg_lines = []
                    msg_lines.append(header_line)
                    msg_lines.append(f"⏰时间(北京): {time_str}")
                    msg_lines.append("------------------")
                    
                    stocks = latest_trade.get('rebalancing_histories', [])
                    for stock in stocks:
                        name = stock.get('stock_name', stock.get('stock_symbol', '未知'))
                        prev_w = stock.get('prev_weight_adjusted') or 0.0
                        target_w = stock.get('target_weight') or 0.0
                        change = target_w - prev_w
                        
                        action = "系统" if category == 'sys_rebalancing' else ("买入" if change > 0 else "卖出")
                        if abs(change) > 0.1:
                            msg_lines.append(f"{action} {name}: {prev_w}% -> {target_w}%")
                    
                    # --- 3. 生成正文 (Msg Body) ---
                    msg_body = "\n".join(msg_lines)
                    
                    # --- 4. 发送逻辑 (Bark) ---
                    # 判断依据：除了表头(3行)之外有变动，或者特殊类别，或者状态发生变更(pending->success)
                    if len(msg_lines) > 3 or category == 'sys_rebalancing' or '❓' in status_str or is_status_update:
                        # 特殊备注
                        if category == 'sys_rebalancing':
                            msg_body += "\n(系统自动触发，非主理人操作)"
                        elif '❓' in status_str:
                            msg_body += f"\n(发现新类型: {category}，请人工检查)"
                        elif is_status_update:
                             msg_body += f"\n(状态更新: {last_status} -> {current_status})"
                        
                        send_bark(title, msg_body, symbol)
                    else:
                        # 只有表头，说明全是微调
                        msg_body += "\n(微调仓，变动幅度均 < 0.1%)"
                    
                    # --- 5. 存入历史 ---
                    latest_trade['summary_text'] = msg_body
                    log_history_to_db(symbol, latest_trade)
                    
                    # 更新状态 (存储 Dict)
                    saved_data[symbol] = {
                        'id': current_id,
                        'status': current_status
                    }
                    save_data_to_db(DB_KEY_STATUS, saved_data)
                else:
                    print(f"[{full_name}] 无新调仓")
        return True # 成功执行
        
    except Exception as e:
        print(f"[{full_name}] 运行出错: {e}")
        return True # 异常不因单个失败而中断整体（除非是Cookie问题）

def init_session():
    """初始化全局 Session，加载 Cookies"""
    from requests.utils import cookiejar_from_dict
    
    # 1. 解析 Secrets 中的基础 Cookie String -> Dict
    # 这些是“底包”，包含核心身份信息
    initial_cookies = {}
    if COOKIE_STR:
        for item in COOKIE_STR.split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                initial_cookies[k] = v
    
    # 2. 尝试从 Redis 加载“最新”的动态 Cookie
    # 这些是“补丁”，包含最新的风控令牌(acw_tc等)，会覆盖底包里的旧值
    redis_cookies = get_cookies_from_db()
    if redis_cookies:
        print("✅ 从数据库加载了持久化 Cookies")
        initial_cookies.update(redis_cookies)
    
    # 3. 装载到 Session
    SESSION.cookies = cookiejar_from_dict(initial_cookies)

def run_monitor_loop(saved_data):
    """执行监控主循环 (返回: 是否遇到严重错误)"""
    for symbol, name in CUBE_DICT.items():
        success = monitor_one_cube(symbol, name, saved_data)
        if not success:
            # 遇到 Cookie 失效，无需继续
            return True # Has Error = True
        time.sleep(1) # 礼貌请求
    
    return False # Has Error = False

def main():
    # 1. 初始化鉴权
    init_session()
    
    # 2. 读取历史状态
    saved_data = get_data_from_db(DB_KEY_STATUS)
    
    # 3. 开始轮询
    auth_failed = run_monitor_loop(saved_data)

    # 4. 收尾保存
    save_data_to_db(DB_KEY_STATUS, saved_data)
    save_cookies_to_db() # 只有成功执行完才值得保存新Cookie
    
    # 5. 错误处理
    if auth_failed:
        print("❌ 监测到 Cookie 失效或认证错误，标记 Action 为失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
