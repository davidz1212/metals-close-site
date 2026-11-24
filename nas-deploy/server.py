"""本地/云端启动入口：python server.py，监听单端口。"""
from __future__ import annotations

import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, log_level="info")
