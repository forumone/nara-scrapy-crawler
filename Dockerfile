# Use a lightweight Python image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies (sometimes needed for building Python crypto libs)
RUN apt-get update && apt-get install -y gcc libffi-dev libssl-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Scrapy project
COPY . .

# Make the pipeline entry point executable
RUN chmod +x scrape_index_pipeline

# Set the Entrypoint
# When AWS Batch starts this container, it will run this script - the job
# definition's command args supply the subcommand and site, e.g.
# ["reindex", "clintonwhitehouse1"] or ["crawl-and-reindex", "--all"].
ENTRYPOINT ["./scrape_index_pipeline"]