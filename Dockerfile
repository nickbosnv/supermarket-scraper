FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py favourites.py matching.py supermarket_scraper.py ./
COPY static static
COPY templates templates
COPY meal_planner meal_planner

ENV PYTHONUNBUFFERED=1 \
    FAVOURITES_FILE=/data/favourites.json \
    MEAL_PLANNER_DATA=/data/meal_planner
EXPOSE 5000
CMD ["python", "app.py"]
