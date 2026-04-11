#!/usr/bin/env python3
"""
Render start script for the auth backend.
Render runs this via: python start.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        workers=2,
        log_level="info",
    )
