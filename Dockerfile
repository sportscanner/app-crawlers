# Use an official Python runtime as a parent image
FROM python:3.10-slim-bookworm

# Set the working directory to /app
WORKDIR /app

# Install necessary system dependencies for Playwright's Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl vim dnsutils ca-certificates gnupg make iputils-ping \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libexpat1 libatspi2.0-0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libdrm2 libxcb1 libxkbcommon0 libasound2 \
    fonts-liberation libcurl4 xdg-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*  # Clean up

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Install any needed packages specified in requirements.txt
RUN make setup

# Install Playwright browsers
RUN pip install playwright && playwright install --with-deps chromium

# Expose the port that Streamlit will run on
EXPOSE 80

CMD ["fastapi", "run", "sportscanner/api/root.py", "--port", "80"]

