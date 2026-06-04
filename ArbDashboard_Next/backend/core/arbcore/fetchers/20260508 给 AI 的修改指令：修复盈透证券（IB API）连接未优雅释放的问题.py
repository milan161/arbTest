给 AI 的修改指令：修复盈透证券（IB API）连接未优雅释放的问题
【背景说明】 我提供给你的 Python 代码中使用了盈透证券（Interactive Brokers）的 API（ibapi）进行数据获取或交易。目前该程序存在一个生命周期管理的隐患：在程序停止、重启或因为异常退出时，没有主动调用 IB API 的断开连接方法。

这会导致 TWS/IB Gateway 端产生“僵尸连接（Zombie Connections）”，旧的 Client ID 持续被占用，最终引发 Max number of clients reached 或 Client ID already in use 的严重报错。

【你的任务】 请帮我重构和修复这段代码，为其添加“优雅断开（Graceful Shutdown）”机制。具体要求如下：

引入退出处理模块：使用 Python 内置的 atexit 模块来捕获程序的退出事件。
编写清理函数：编写一个名为 cleanup_ib_connection()（或类似名称）的函数。在该函数内部：
检查 IB 客户端实例（如 ib_client, ib_reader, app 等，请根据我的代码推断具体变量名）是否已实例化且非空。
包含 try...except 异常捕获块，防止断开过程中的报错阻塞程序的最终退出。
调用该实例的 .disconnect() 方法。
打印清晰的日志（如：“正在断开 IB API 连接...” 和 “连接已成功断开释放”）。
注册清理函数：使用 atexit.register() 注册该清理函数。
注意代码执行顺序：请确保变量的作用域正确。必须在声明了全局的 IB 客户端变量之后，且在任何会产生阻塞（Blocking）的主循环（如 while True:, app.run(), socket.accept()）之前注册这个退出清理函数。
【参考模板】 请参考以下逻辑结构融入我的代码中：

import atexit

# 1. 假设这是原代码中的 IB 客户端实例化
# ib_instance = MyIBClient(...)

def cleanup_ib_connection():
    """优雅断开 IB 连接，防止 Client ID 被挂起占用"""
    global ib_instance # 替换为实际的变量名
    if ib_instance:
        print("\n🛑 [系统] 捕获到退出信号，准备断开 IB API 连接...")
        try:
            ib_instance.disconnect()
            print("✅ [系统] IB API 连接已安全断开。")
        except Exception as e:
            print(f"⚠️ [系统] 断开 IB 连接时发生异常: {e}")

# 2. 在主阻塞代码运行前注册
atexit.register(cleanup_ib_connection)

if __name__ == '__main__':
    # 3. 这里是原有的阻塞主逻辑
    # start_main_loop() 

请阅读我的代码，并严格按照上述要求给我一份修改后的完整安全代码。

把上面这段说明保存下来，下次遇到有类似 IB API 调用的 Python 脚本，直接把这段文字和代码一起发过去，任何优秀的代码助手都能完美地帮你把隐患排除掉！