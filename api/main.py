"""FastAPI 应用入口。"""

from fastapi import FastAPI


app = FastAPI(title="DisvorAI API", version="1.0.0")


@app.get("/api/v1/health")
def health_check():
    """返回服务健康状态。"""
    return {"status": "ok"}

