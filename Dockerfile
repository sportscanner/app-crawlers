# Use an official Python runtime as a parent image
FROM python:3.10-slim-bookworm

# Set the working directory to /app
WORKDIR /app

# Ensure apt package list is up-to-date and install dependencies
RUN apt-get update && apt-get install -y \
    curl ca-certificates gnupg \
    make iputils-ping \
    libdbus-1-3 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libxfixes3 \
    libxkbcommon0 \
    libnss3 libatk1.0-0 libxcomposite1 libxrandr2 \
    libasound2 libpangocairo-1.0-0 libxdamage1 libgbm1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*  # Clean up cache

COPY . .

# Install any needed packages specified in requirements.txt
RUN make setup

# Expose the port that Streamlit will run on
EXPOSE 80

CMD ["fastapi", "run", "sportscanner/api/root.py", "--port", "80"]

