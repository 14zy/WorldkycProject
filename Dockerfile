FROM python:3.10
WORKDIR /WorldkycProject
RUN apt update && apt install -y nano jq curl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "main.py"]
