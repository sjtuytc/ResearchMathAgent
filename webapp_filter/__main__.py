"""Allow running as: python -m webapp_filter"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("webapp_filter.server:app", host="127.0.0.1", port=8012, reload=False)
