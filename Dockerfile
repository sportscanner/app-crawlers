# Use an official Python runtime as a parent image
FROM python:3.10-slim-bookworm

# Install make and any other dependencies
RUN apt-get update && apt-get install -y make

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN make setup

# Expose the port that Streamlit will run on
EXPOSE 80

CMD ["fastapi", "run", "sportscanner/api/", "--port", "80"]

