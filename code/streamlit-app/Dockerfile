# 明確指定基礎映像架構
FROM --platform=linux/amd64 python:3.12

# 設定工作目錄
WORKDIR /app

# 複製依賴檔案
COPY requirements.txt ./requirements.txt

# 安裝 Python 依賴
RUN pip3 install -r requirements.txt --no-cache-dir

# 複製應用程式檔案
COPY *.py ./
COPY unknown ./unknown

# 暴露 Streamlit 預設連接埠
EXPOSE 8501

# 健康檢查
HEALTHCHECK --interval=600s --timeout=2s --retries=12 \
    CMD ["curl", "-f", "http://localhost:8501/"]

# 啟動 Streamlit 應用程式
ENTRYPOINT ["streamlit", "run", "app.py", "--server.headless", "true", "--browser.serverAddress=0.0.0.0", "--browser.gatherUsageStats", "false"]

# 使用非 root 使用者執行
USER 1001