# M3U Stream Monitor (m3u-monitor)

## 1. Overview

The M3U Stream Monitor is a web-based application designed to continuously monitor the health and performance of video streams from one or more M3U playlists. It runs as a Docker container, providing a user-friendly web interface to track stream availability, resolution, frame rate, and load times.

The application periodically probes each stream in your configured M3U sources, logs the performance data to a persistent database, and visualizes this data through interactive graphs. This allows you to easily identify problematic streams, track performance over time, and manage your M3U sources directly from the UI.

---

## 2. Key Features

* **Multi-Source Management:** Add, edit, and delete multiple M3U playlists directly from the web interface. All sources are stored persistently.
* **Overview Dashboard:** A main dashboard provides a high-level view of all your M3U sources, with an overall availability status and a collapsible list of individual streams and their latest status.
* **Detailed Analytics:** Each M3U source has a dedicated page with interactive graphs for every stream, plotting:
    * Vertical Resolution (e.g., 1080p, 720p)
    * Frame Rate (fps)
    * Load Time (ms)
* **Stream Comparison:** A dedicated page to select any two streams from any source and overlay their performance graphs for direct comparison.
* **Automatic TVG Logo Display:** Automatically parses and displays `tvg-logo` images from your M3U file next to each stream.
* **Persistent Data:** Uses a SQLite database to store all historical performance data, which persists across container restarts.
* **Easy Deployment:** Deploys as a single Docker container managed by a simple `docker-compose.yml` file.

---

## 3. Screenshots

### Main Overview Dashboard

This page shows all configured M3U sources as collapsible cards, each with an overall availability status and a list of its individual streams.

<img width="383" alt="Screenshot 2025-07-03 at 9 01 56 pm" src="https://github.com/user-attachments/assets/b1667151-ffec-4b49-a7de-406d87b8515a" />

### Detailed Stream Dashboard

This page displays the detailed performance graphs for every stream within a single M3U source.

<img width="1435" alt="m3u-monitor Dashboard" src="https://github.com/user-attachments/assets/7625a504-9bea-4b84-8330-262a9a39c0a3" />

<img width="1423" alt="Screenshot 2025-07-03 at 9 00 30 pm" src="https://github.com/user-attachments/assets/2f4cdb5d-451f-4044-aef0-405850ba069b" />

### Stream Comparison Page

This page allows you to select any two streams to compare their load times on an overlayed graph.

<img width="1435" alt="m3u-monitor Comparison Page" src="https://github.com/user-attachments/assets/8e3926ee-3ea9-4163-9dc3-0bc5ea312406" />


---

## 4. Prerequisites

Before you begin, ensure you have the following installed on your system:

* **Docker:** [Install Docker](https://docs.docker.com/get-docker/)
* **Docker Compose:** [Install Docker Compose](https://docs.docker.com/compose/install/) (usually included with Docker Desktop)

---

## 5. Project Structure

Your project should be organized with the following file structure:

```
m3u-monitor/
├── app.py              # The core Flask application
├── Dockerfile          # Instructions to build the Docker image
├── docker-compose.yml  # Defines and configures the application service
├── requirements.txt    # Python dependencies
└── templates/
    ├── 404.html
    ├── add_m3u.html
    ├── base.html
    ├── compare.html
    ├── edit_m3u.html
    ├── index.html
    └── m3u_dashboard.html
```

---

## 6. Configuration and Deployment

Follow these steps to configure and deploy the M3U Stream Monitor.

### Step 1: Clone or Download the Project Files

Ensure all the project files listed in the structure above are in a single directory on your machine.

### Step 2: Configure Environment Variables (Optional)

You can customize the application's behavior by editing the `environment` section in the `docker-compose.yml` file.

```yaml
services:
  monitor:
    # ...
    environment:
      - TEST_RATE=600          # Check interval in seconds (Default: 600 = 10 minutes)
      - PORT=2029              # Port the web interface runs on (Default: 2029)
      - FFPROBE_TIMEOUT=30     # Timeout for stream probes in seconds (Default: 15)
```

Already have a docker-compose file? No worries, save the m3u-monitor.Dockerfile in the same location, and add this to your docker-compose.yaml.

```
m3u-monitor:
    build:
      context: . # Assumes the Dockerfile is in the same directory as the docker-compose.yml
      dockerfile: m3u-monitor.Dockerfile # Explicitly specifies the Dockerfile name (if different)
    container_name: m3u-moniter
    environment:
      - PUID=1000             # Not required. Change as you like
      - PGID=1000             # Not required. Change as you like
      - PORT=2029
      - TEST_RATE=1800        # Sets the check interval to 1,800 seconds (30 minutes).
      - PORT=2029             # Sets the port the application runs on Must match the container port.
      - FFPROBE_TIMEOUT=15    # Sets the timeout for each stream check.
      - TZ=COUNTRY/CITY
    restart: unless-stopped
    ports:
      - "2029:2029"           # If using gluetun - add this to the gluetun ports, not here and uncomment the lines below.
    #depends_on:
    #  - gluetun
    #network_mode: "service:gluetun"

```

### Step 3: Build and Start the Container
Open a terminal in the root of the project directory and run the following command:

```
docker compose up --build -d
```
> --build: This flag tells Docker Compose to build the image from your Dockerfile before starting. You should use this the first time you run it or after making any code changes.
> -d: This runs the container in detached mode (in the background).

### Step 4: Access the Web Interface
Once the container is running, open your web browser and navigate to:
```
http://localhost:2029
```
> (Replace localhost with the IP address of your server if you are running it remotely).

## 7. How to Use the Application
Add an M3U Source:
Click the "+ Add Source" button in the top-right corner.
Fill in a descriptive name and the full URL of your M3U playlist.
Click "Add Source". The application will immediately perform a first check on the new source.
View the Dashboard:
The main page shows a card for each M3U source.
Click on a card's header to expand or collapse the list of individual streams and their latest status.
The overall status (green, orange, red) is based on the availability percentage over the last 24 hours.
View Detailed Graphs:
On the main dashboard, click the "Details" button on any source card.
This will take you to a page with detailed performance graphs for every stream in that M3U.
Click on any stream's header to expand or collapse its graph.
Compare Streams:
Click the "Compare Streams" button in the main navigation bar.
Use the dropdown menus to select any two streams from any of your sources.
Click "Compare" to see their load times plotted on the same graph.
Edit or Delete a Source:
On the main dashboard, use the "Edit" or "Delete" buttons on any source card to manage your M3U sources.

## 8. Managing the Application
To view logs:
```
docker compose logs -f
```
To stop the application:
```
docker compose down
```
To restart the application:
```
docker compose restart
```
