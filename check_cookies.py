"""
启动前 Cookie 预检工具

用法:
  python -m academic_spiders.utils.auth check     # 检查 Cookie 有效性
  python -m academic_spiders.utils.auth login -u <账号> -p <密码>  # 自动登录
"""

from academic_spiders.utils.auth import main

if __name__ == "__main__":
    main()
