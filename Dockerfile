FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install discord.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
