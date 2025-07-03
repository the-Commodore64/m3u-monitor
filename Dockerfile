# Use an official lightweight Python runtime as a parent image
FROM python:3.9-slim

# Install ffmpeg
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy dependency file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code
COPY . .

# Create directories for persistent data and static files
RUN mkdir -p /app/data /app/static/frames

# Expose the port the app runs on
EXPOSE 2029

# Define environment variables (these can be overridden at runtime)
ENV TEST_RATE=1800
ENV PORT=2029
ENV PYTHONUNBUFFERED=1

# Command to run the application using Gunicorn WSGI server
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:2029", "--timeout", "120", "app:app"]
