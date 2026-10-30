FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
COPY benchmarks/p2/results ./benchmarks/p2/results
COPY run.py ./
EXPOSE 8000
CMD ["python", "run.py", "--host", "0.0.0.0"]
