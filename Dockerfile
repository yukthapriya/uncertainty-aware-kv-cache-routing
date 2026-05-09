FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kv_router ./kv_router
COPY mock_node.py ./mock_node.py

EXPOSE 8000

CMD ["uvicorn", "kv_router.router:app", "--host", "0.0.0.0", "--port", "8000"]