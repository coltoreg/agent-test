FROM public.ecr.aws/lambda/python:3.11@sha256:58834a0d4d7f86326b6c91d516c66fbe8e91ccd3646ceba4025a66a7a8906e81

# 安裝系統更新和必要工具
RUN yum update --security -y && \
    yum install -y \
    fontconfig \
    freetype \
    wget \
    unzip \
    && yum clean all

# 建立字體目錄
RUN mkdir -p /usr/share/fonts/opentype/noto

# 下載並安裝 Noto Sans CJK TC 字體（包含 Regular 和 Medium）
RUN cd /tmp && \
    # 下載完整的 Noto Sans CJK TC 字體包
    wget -q https://github.com/googlefonts/noto-cjk/releases/download/Sans2.004/03_NotoSansCJK-OTC.zip && \
    unzip -q 03_NotoSansCJK-OTC.zip && \
    # 只複製需要的繁體中文字體
    cp NotoSansCJK-Regular.ttc /usr/share/fonts/opentype/noto/ && \
    cp NotoSansCJK-Medium.ttc /usr/share/fonts/opentype/noto/ && \
    # 清理暫存檔案
    rm -rf /tmp/*

# 或者使用單獨的 OTF 檔案（檔案較小）
# RUN cd /usr/share/fonts/opentype/noto && \
#     wget -q https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf && \
#     wget -q https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Medium.otf

# 更新字體快取
RUN fc-cache -fv

# 驗證字體安裝
RUN fc-list | grep -i "Noto Sans CJK TC" || echo "Warning: Noto Sans CJK TC fonts not found"

# 設定字體環境變數
ENV FONTCONFIG_PATH=/etc/fonts
ENV LANG=zh_TW.UTF-8
ENV LC_ALL=zh_TW.UTF-8
ENV PYTHONIOENCODING=utf-8

# 安裝 Python 套件
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --upgrade pip setuptools wheel --no-cache-dir
RUN pip install --no-cache-dir -r requirements.txt

# 安裝 PyTorch CPU 版本
RUN pip install --no-cache-dir torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu

# 複製應用程式碼
COPY . ${LAMBDA_TASK_ROOT}

# 設定執行命令
CMD ["index.get_response"]

# 設定使用者和健康檢查
USER 1001
HEALTHCHECK --interval=600s --timeout=2s --retries=12 \
    CMD ["cat", "requirements.txt"]