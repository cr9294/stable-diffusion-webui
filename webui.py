# 从__future__模块导入annotations，启用对类型提示的支持
from __future__ import annotations

import os
import time

# 导入自定义的模块
from modules import timer
from modules import initialize_util
from modules import initialize

# 初始化启动计时器
startup_timer = timer.startup_timer
startup_timer.record("launcher")

# 导入必要的模块和库
initialize.imports()

# 检查版本信息
initialize.check_versions()


# 创建API的函数，接收一个FastAPI应用实例，并返回初始化的API对象
def create_api(app):
    from modules.api.api import Api
    from modules.call_queue import queue_lock

    api = Api(app, queue_lock)
    return api


# 仅启动API的函数
def api_only():
    from fastapi import FastAPI
    from modules.shared_cmd_options import cmd_opts

    # 初始化
    initialize.initialize()

    # 创建FastAPI应用
    app = FastAPI()
    initialize_util.setup_middleware(app)
    api = create_api(app)

    # 导入脚本回调模块，并执行相关回调函数
    from modules import script_callbacks
    script_callbacks.before_ui_callback()
    script_callbacks.app_started_callback(None, app)

    # 打印启动时间，并启动API
    print(f"Startup time: {startup_timer.summary()}.")
    api.launch(
        server_name=initialize_util.gradio_server_name(),
        port=cmd_opts.port if cmd_opts.port else 7861,
        root_path=f"/{cmd_opts.subpath}" if cmd_opts.subpath else ""
    )


# 启动包含用户界面（UI）的函数
def webui():
    from modules.shared_cmd_options import cmd_opts

    # 获取命令行参数，指示是否启动API
    launch_api = cmd_opts.api

    # 初始化
    initialize.initialize()

    # 导入相关模块
    from modules import shared, ui_tempdir, script_callbacks, ui, progress, ui_extra_networks

    while 1:
        # 如果设置了清理临时目录选项，执行临时目录清理操作
        if shared.opts.clean_temp_dir_at_start:
            ui_tempdir.cleanup_tmpdr()
            startup_timer.record("cleanup temp dir")

        # 执行UI前回调函数
        script_callbacks.before_ui_callback()
        startup_timer.record("scripts before_ui_callback")

        # 创建用户界面
        shared.demo = ui.create_ui()
        startup_timer.record("create ui")

        # 如果不禁用Gradio队列，将一些示例数据加入队列
        if not cmd_opts.no_gradio_queue:
            shared.demo.queue(64)

        # 获取Gradio认证凭证
        gradio_auth_creds = list(initialize_util.get_gradio_auth_creds()) or None

        # 配置是否自动在浏览器中打开
        auto_launch_browser = False
        if os.getenv('SD_WEBUI_RESTARTING') != '1':
            if shared.opts.auto_launch_browser == "Remote" or cmd_opts.autolaunch:
                auto_launch_browser = True
            elif shared.opts.auto_launch_browser == "Local":
                auto_launch_browser = not cmd_opts.webui_is_non_local

        # 启动Gradio服务器
        app, local_url, share_url = shared.demo.launch(
            share=cmd_opts.share,
            server_name=initialize_util.gradio_server_name(),
            server_port=cmd_opts.port,
            ssl_keyfile=cmd_opts.tls_keyfile,
            ssl_certfile=cmd_opts.tls_certfile,
            ssl_verify=cmd_opts.disable_tls_verify,
            debug=cmd_opts.gradio_debug,
            auth=gradio_auth_creds,
            inbrowser=auto_launch_browser,
            prevent_thread_lock=True,
            allowed_paths=cmd_opts.gradio_allowed_path,
            app_kwargs={
                "docs_url": "/docs",
                "redoc_url": "/redoc",
            },
            root_path=f"/{cmd_opts.subpath}" if cmd_opts.subpath else "",
        )

        startup_timer.record("gradio launch")

        # 禁用Gradio的自动CORS策略，以增强安全性
        app.user_middleware = [x for x in app.user_middleware if x.cls.__name__ != 'CORSMiddleware']

        # 设置中间件
        initialize_util.setup_middleware(app)

        # 设置进度API和UI API
        progress.setup_progress_api(app)
        ui.setup_ui_api(app)

        # 如果启动API，创建API对象
        if launch_api:
            create_api(app)

        # 添加额外的网络页面到演示
        ui_extra_networks.add_pages_to_demo(app)

        # 记录启动时长和执行app_started_callback回调函数
        startup_timer.record("add APIs")
        with startup_timer.subcategory("app_started_callback"):
            script_callbacks.app_started_callback(shared.demo, app)

        # 打印启动时间
        timer.startup_record = startup_timer.dump()
        print(f"Startup time: {startup_timer.summary()}.")

        try:
            # 在循环中等待服务器命令，支持停止或重新启动
            while True:
                server_command = shared.state.wait_for_server_command(timeout=5)
                if server_command:
                    if server_command in ("stop", "restart"):
                        break
                    else:
                        print(f"Unknown server command: {server_command}")
        except KeyboardInterrupt:
            print('Caught KeyboardInterrupt, stopping...')
            server_command = "stop"

        # 如果收到停止命令，关闭服务器
        if server_command == "stop":
            print("Stopping server...")
            shared.demo.close()
            break

        # 禁用后续UI重新加载时在浏览器中自动启动的选项
        os.environ.setdefault('SD_WEBUI_RESTARTING', '1')

        # 重新启动UI
        print('Restarting UI...')
        shared.demo.close()
        time.sleep(0.5)
        startup_timer.reset()
        script_callbacks.app_reload_callback()
        startup_timer.record("app reload callback")
        script_callbacks.script_unloaded_callback()
        startup_timer.record("scripts unloaded callback")
        # 重新初始化，重新加载脚本模块
        initialize.initialize_rest(reload_script_modules=True)


# 如果脚本作为主程序执行，根据命令行参数选择启动api_only()或webui()
if __name__ == "__main__":
    from modules.shared_cmd_options import cmd_opts

    if cmd_opts.nowebui:
        api_only()
    else:
        webui()
