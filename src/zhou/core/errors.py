class ZhouError(Exception):
    """Base exception for zhou CLI."""


class ConfigNotFoundError(ZhouError):
    def __init__(self) -> None:
        message = (
            "未找到配置文件。请在 %USERPROFILE%\\.zhou\\config.toml、config.md，"
            "或 zhou 命令所在目录 / 当前目录下提供配置文件。"
        )
        super().__init__(message)


class InvalidConfigError(ZhouError):
    def __init__(self, field_name: str) -> None:
        super().__init__(f"配置文件中缺少必要字段: {field_name}")


class InvalidToolsConfigError(ZhouError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"tools 配置无效: {detail}")


class ApiRequestError(ZhouError):
    pass


class MemoryInitError(ZhouError):
    pass
