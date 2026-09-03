#!/usr/bin/env python
"""
academic-spiders 运行模式切换命令行入口 (配置类方案)

用法:
  python env.py list                      # 列出所有模式 + 当前生效模式
  python env.py current                   # 查看当前激活配置 (数据库/日志/输出)
  python env.py switch <test|dev|prod>    # 切换模式 (只改 .env 中 ACADEMIC_MODE)
  python env.py init                      # 从 .env.secrets.example 初始化 .env.secrets

实现: academic_spiders.config (ConfigBase + registry)
配置定义: academic_spiders/config/modes.py (可提交)
密钥仓库: 项目根 .env.secrets (gitignored, 含真实密钥)
"""

import argparse
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()

from academic_spiders.config import (
    get_active_config,
    get_active_mode,
    list_modes,
    set_active_mode,
)
from academic_spiders.config.registry import MODE_CLASSES
from academic_spiders.config.secrets import DEFAULT_SECRETS_FILE, EXAMPLE_SECRETS_FILE
from academic_spiders.utils.logging_config import PROJECT_ROOT


def cmd_list():
    print(f"配置仓库: academic_spiders/config/modes.py")
    print(f"密钥文件: {DEFAULT_SECRETS_FILE}")
    print(f"当前开关: ACADEMIC_MODE={get_active_mode()}")
    print()
    print(f"{'模式':<6}{'当前':<6}{'说明':<10}{'数据库':<16}{'日志目录'}")
    print("-" * 72)
    for mode, label, is_active in list_modes():
        mark = "◀" if is_active else ""
        cls = MODE_CLASSES[mode]
        # 静态取非敏感类属性, 不实例化
        db = cls.MYSQL_DATABASE
        log = f"logs/{mode}" if mode != "prod" else "logs"
        print(f"{mode:<6}{mark:<6}{label:<10}{db:<16}{log}")
    print(f"\n切换: python env.py switch <test|dev|prod>")


def cmd_current():
    cfg = get_active_config(refresh=False)
    print(f"当前模式: {cfg.mode} ({cfg.label})")
    print(f"ACADEMIC_MODE={get_active_mode()}")
    print()
    print(cfg.summarize())


def cmd_switch(mode: str, yes: bool):
    active = get_active_mode()
    if active == mode:
        print(f"当前已经是模式 {mode}, 无需切换")
        return

    if mode == "prod" and not yes:
        resp = input(
            "警告: 切换到 prod 将连接远程生产库 (pubscholar)!\n"
            "确认继续? (yes/no): "
        ).strip().lower()
        if resp not in ("y", "yes"):
            print("已取消")
            return

    cfg = set_active_mode(mode, persist=True)
    print(f"✅ 已切换到模式 {mode}")
    print(f"   数据库: {cfg.MYSQL_DATABASE} @ {cfg.MYSQL_HOST}:{cfg.MYSQL_PORT}")
    print(f"   日志:   {cfg.log_dir}")
    print(f"   JSON:   {cfg.json_output_dir}")


def cmd_init(force: bool):
    if DEFAULT_SECRETS_FILE.exists() and not force:
        print(f"{DEFAULT_SECRETS_FILE} 已存在 (用 --force 覆盖)")
        return
    if not EXAMPLE_SECRETS_FILE.exists():
        print(f"模板不存在: {EXAMPLE_SECRETS_FILE}", file=sys.stderr)
        sys.exit(1)
    shutil.copyfile(EXAMPLE_SECRETS_FILE, DEFAULT_SECRETS_FILE)
    print(f"已从模板创建 {DEFAULT_SECRETS_FILE}")
    print("请编辑该文件填入真实密钥 (MYSQL_PASSWORD 等)")


def main():
    parser = argparse.ArgumentParser(
        prog="env.py",
        description="academic-spiders 运行模式切换 (test/dev/prod)",
    )
    parser.add_argument(
        "--root", default=str(PROJECT_ROOT),
        help="项目根目录 (默认自动检测)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出所有模式与当前状态")
    sub.add_parser("current", help="查看当前激活配置")

    p_init = sub.add_parser("init", help="初始化 .env.secrets")
    p_init.add_argument("--force", action="store_true", help="覆盖已有文件")

    p_switch = sub.add_parser("switch", help="切换到指定模式 (写入 .env ACADEMIC_MODE)")
    p_switch.add_argument("mode", help="目标模式")
    p_switch.add_argument("-y", "--yes", action="store_true",
                          help="切换到 prod 时跳过确认")

    args = parser.parse_args()
    try:
        if args.command == "list":
            cmd_list()
        elif args.command == "current":
            cmd_current()
        elif args.command == "init":
            cmd_init(args.force)
        elif args.command == "switch":
            cmd_switch(args.mode.lower(), args.yes)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
