# AWS Serverless Web Crawler for Archived Sites

This project is a containerized **Scrapy** crawler designed to run on **AWS Batch**. It serves as the data collection engine for an aggregated search system.

It is designed to crawl static/archived websites, normalize the data into a strict schema, and output JSON files to **Amazon S3**. An S3 Event Trigger then handles ingestion into **AWS OpenSearch**.

## 🏗 Architecture

**Drupal (Admin)** ➔ **AWS SQS** ➔ **AWS Batch (This Repo)** ➔ **S3 Bucket** ➔ **Lambda** ➔ **OpenSearch**

1.  **Trigger:** Drupal sends a message to SQS with a URL and Site ID.
2.  **Compute:** AWS Batch spins up a Docker container (this project).
3.  **Crawl:** Scrapy crawls the site using the `generic_crawl` spider.
4.  **Storage:** JSON results are streamed directly to S3.
5.  **Ingest:** A separate Lambda function detects the new file and pushes it to OpenSearch.

## 🚀 Setup & Installation

### Prerequisites
* Python 3.9+
* Docker
* AWS CLI (configured)

### Local Setup

# 1. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

# 2. Install dependencies
```bash
pip install -r requirements.txt
```

---

## 🕷️ Running Locally (Development)

You can run the spider locally to test extraction logic without spinning up Docker.

### Method 1: Dry Run (No S3 Upload)
Prints JSON to the terminal. Best for debugging selectors and cleaning logic.

```bash
scrapy crawl generic_crawl \
  -a url="[https://www.example.com/](https://www.example.com/)" \
  -a site_id="local_dev_test" \
  -a urls_to_skip="/login,/admin,/calendar" \
  -s FEED_URI=stdout \
  -s FEED_FORMAT=json \
  -s CLOSESPIDER_PAGECOUNT=10
```

## 📂 Project Structure

`spiders/generic_crawl.py`: The core spider. Uses CrawlSpider and LinkExtractors to walk the site. Dynamically accepts url and urls_to_skip.

`items.py`: Defines the strict JSON schema (Title, Full Text, Teaser, Date).

`run_crawl.sh`: The Entrypoint script used by the Docker container. It accepts CLI args and translates them into Scrapy commands.

Dockerfile: Python 3.9 Slim image configuration.


## 🛠 Deployment to AWS

### Authenticate Docker to ECR.
```commandline
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 756132184927.dkr.ecr.us-east-2.amazonaws.com
```

### Build to make a new image.
```commandline
docker build --platform linux/amd64 -t archive-crawler .
```

### Create the history tag:

Where `[tag]` is the next iteration of the tag.

```commandline
docker tag archive-crawler:latest 756132184927.dkr.ecr.us-east-2.amazonaws.com/archive-crawler:[tag]
```

### Update the current pointer

```commandline
docker tag archive-crawler:latest 756132184927.dkr.ecr.us-east-2.amazonaws.com/archive-crawler:latest
```

### Push to AWS
```commandline
docker push 756132184927.dkr.ecr.us-east-2.amazonaws.com/archive-crawler:latest
```