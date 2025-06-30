# 使用 AWS Lambda 的官方 Python 3.11 基底映像
FROM public.ecr.aws/lambda/python:3.11

# ==== 複製程式碼 ====
COPY . ${LAMBDA_TASK_ROOT}

# ==== 安裝 Python 依賴 ====
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# ==== 設定 Lambda handler ====
# 指向 index.py 中的 lambda_handler 函數
CMD ["index.lambda_handler"]
