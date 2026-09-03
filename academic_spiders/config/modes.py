"""
三种运行模式的具体配置 (继承 ConfigBase)

非敏感值在此硬编码 (可提交); 敏感值 (密码, 以及远程 host 等) 由 secrets
文件 (.env.secrets, gitignored) 在构造时合并。字段约定沿用 MYSQL_* 大写,
与 settings.py / pipelines / extensions 的读取方式一致。
"""

from academic_spiders.config.base import ConfigBase


class TestConfig(ConfigBase):
    """本地测试模式: academicdb_test @ localhost"""
    mode = "test"
    label = "本地测试"
    MYSQL_HOST = "localhost"
    MYSQL_PORT = 3306
    MYSQL_USER = "root"
    MYSQL_DATABASE = "academicdb_test"
    json_subdir = "test"          # output/test/ + logs/test/


class DevConfig(ConfigBase):
    """本地开发模式: academicdb @ localhost"""
    mode = "dev"
    label = "本地开发"
    MYSQL_HOST = "localhost"
    MYSQL_PORT = 3306
    MYSQL_USER = "root"
    MYSQL_DATABASE = "academicdb"
    json_subdir = "dev"           # output/dev/ + logs/dev/


class ProdConfig(ConfigBase):
    """远程生产模式: pubscholar @ 远程主机 (数据交付目标)"""
    mode = "prod"
    label = "远程生产"
    # host 为敏感基础设施信息, 默认空串, 由 .env.secrets 提供 (避免入库)
    MYSQL_HOST = ""
    MYSQL_PORT = 3306
    MYSQL_USER = ""
    MYSQL_DATABASE = "pubscholar"
    json_subdir = ""              # output/ + logs/
