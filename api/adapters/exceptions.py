"""引擎适配层异常。"""


class GeoEngineError(RuntimeError):
    """引擎执行失败，不应终止 worker 进程。"""

    def __init__(self, message: str):
        self.message = str(message)
        super().__init__(self.message)

