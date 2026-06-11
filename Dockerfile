FROM selenium/standalone-chrome:latest

USER root
RUN pip install discord.py selenium

WORKDIR /app
COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
