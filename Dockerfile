FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install discord.py
CMD ["python", "bot.py"]
