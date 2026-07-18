FROM python:3.11-slim

# Не root: приложение работает от непривилегированного пользователя
RUN useradd --create-home --shell /usr/sbin/nologin qosyu

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
RUN chown -R qosyu:qosyu /app

USER qosyu
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
