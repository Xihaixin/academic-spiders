#!/usr/bin/env python
"""
academic-spiders 运行模式切换命令行入口

用法:
  python env.py list                      # 列出所有模式 + 当前生效模式
  python env.py current                   # 查看当前 .env 生效配置 (脱敏)
  python env.py switch <test|dev|prod>    # 切换到指定模式并写入 .env
  python env.py switch <mode> --dry-run   # 试运行: 打印将写入的内容, 不落盘
  python env.py init                      # 从 .env.profiles.example 初始化 .env.profiles

实现: academic_spiders.utils.env_manager.EnvManager
Profile 仓库: 项目根 .env.profiles (gitignored, 含真实密钥)
"""

import argparse
import shutil
import sys

from academic_spiders.utils.env_manager import (
    DEFAULT_ENV_FILE,
    EXAMPLE_PROFILES_FILE,
    MODES,
    EnvError,
    EnvManager,
)
from academic_spiders.utils.logging_config import PROJECT_ROOT


def cmd_list(mgr: EnvManager):
    profiles = mgr.read_profiles()
    active = mgr.detect_active_mode()
    print(f"Profile 仓库: {mgr.profiles_file}")
    print(f"当前 .env:   {mgr.env_file}")
    print()
    print(f"{'模式':<6}{'当前':<6}{'数据库':<16}{'主机'}")
    print("-" * 60)
    for p in profiles:
        mark = "◀" if p.mode == active else ""
        env = p.env
        print(
            f"{p.mode:<6}{mark:<6}"
            f"{env.get('MYSQL_DATABASE', ''):<16}"
            f"{env.get('MYSQL_HOST', '')}"
        )
    if not profiles:
        print("(无 profile, 请先运行 python env.py init)")
    if active is None:
        print(f"\n注意: 当前 .env 无法匹配任何 profile (或 .env 不存在)")
    print(f"\n可用命令: python env.py switch <{'|'.join(p.mode for p in profiles)}>")


def cmd_current(mgr: EnvManager):
    env = mgr.read_active_env()
    if not env:
        print(f"{mgr.env_file} 不存在或为空")
        return
    active = mgr.detect_active_mode()
    print(f"当前 .env: {mgr.env_file}")
    print(f"匹配模式:  {active or '(未匹配任何 profile)'}")
    print()
    for key in ("ACADEMIC_MODE", "MYSQL_HOST", "MYSQL_DATABASE",
                "ACADEMIC_JSON_OUTPUT"):
        val = env.get(key)
        if val is not None:
            print(f"{key} = {val}")
    # 密码脱敏
    pw = env.get("MYSQL_PASSWORD")
    if pw is not None:
        masked = pw[:1] + "*" * min(len(pw) - 1, 6)
        print(f"MYSQL_PASSWORD = {masked}")
    others = {k: v for k, v in env.items() if k not in {
        "ACADEMIC_MODE", "MYSQL_HOST", "MYSQL_DATABASE",
        "MYSQL_PASSWORD", "ACADEMIC_JSON_OUTPUT"}}
    if others:
        print("\n其他键:")
        for k, v in others.items():
            print(f"  {k} = {v}")


def cmd_switch(mgr: EnvManager, mode: str, dry_run: bool, yes: bool):
    profile = mgr.get_profile(mode)

    active = mgr.detect_active_mode()
    if active == mode:
        print(f"当前已经是模式 {mode}, 无需切换")
        return

    if mode == "prod" and not yes:
        resp = input(
            "警告: 切换到 prod 将写入远程生产库 (pubscholar)!\n"
            "确认继续? (yes/no): "
        ).strip().lower()
        if resp not in ("y", "yes"):
            print("已取消")
            return

    if dry_run:
        content = mgr.render(mode)
        print(f"[dry-run] 将写入 {mgr.env_file} (模式 {mode}):")
        print("-" * 60)
        print(content)
        return

    mgr.switch(mode)
    print(f"✅ 已切换到模式 {mode}")
    print(f"   数据库: {profile.env.get('MYSQL_DATABASE')} @ {profile.env.get('MYSQL_HOST')}")
    extra_env = mgr.collect_extra()
    if extra_env:
        print(f"   已保留自定义键: {', '.join(extra_env)}")


def cmd_init(mgr: EnvManager):
    if mgr.profiles_file.exists():
        print(f"{mgr.profiles_file} 已存在, 无需初始化")
        return
    if not EXAMPLE_PROFILES_FILE.exists():
        raise EnvError(f"模板不存在: {EXAMPLE_PROFILES_FILE}")
    shutil.copyfile(EXAMPLE_PROFILES_FILE, mgr.profiles_file)
    print(f"已从模板创建 {mgr.profiles_file}")
    print("请编辑该文件填入真实密钥 (MYSQL_PASSWORD / MYSQL_HOST 等)")


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
    sub.add_parser("current", help="查看当前 .env 生效配置")
    p_init = sub.add_parser("init", help="初始化 .env.profiles")
    p_init.add_argument("--force", action="store_true", help="覆盖已有文件")

    p_switch = sub.add_parser("switch", help="切换到指定模式并写入 .env")
    p_switch.add_argument("mode", choices=list(MODES), help="目标模式")
    p_switch.add_argument("--dry-run", action="store_true", help="只打印不落盘")
    p_switch.add_argument("-y", "--yes", action="store_true",
                          help="切换到 prod 时跳过确认")

    args = parser.parse_args()
    mgr = EnvManager()

    try:
        if args.command == "list":
            cmd_list(mgr)
        elif args.command == "current":
            cmd_current(mgr)
        elif args.command == "init":
            if mgr.profiles_file.exists() and not args.force:
                print(f"{mgr.profiles_file} 已存在 (用 --force 覆盖)")
                return
            cmd_init(mgr)
        elif args.command == "switch":
            cmd_switch(mgr, args.mode, args.dry_run, args.yes)
    except EnvError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
