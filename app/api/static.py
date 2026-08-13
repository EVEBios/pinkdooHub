"""允许本地上传根目录延迟创建的静态文件入口。"""

from pathlib import Path

from fastapi.staticfiles import StaticFiles


class DeferredDirectoryStaticFiles(StaticFiles):
    """目录尚未由首次上传创建时返回 404，而不是配置 500。"""

    async def check_config(self) -> None:
        if self.directory is not None and not Path(self.directory).exists():
            return
        await super().check_config()
