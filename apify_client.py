import os
import time
import requests

API = "https://api.apify.com/v2"
TOKEN = os.environ["APIFY_TOKEN"]

GROUPS_ACTOR = "apify~facebook-groups-scraper"
COMMENTS_ACTOR = "apify~facebook-comments-scraper"


def run_actor(actor, payload, timeout=600):
    r = requests.post(f"{API}/acts/{actor}/runs", params={"token": TOKEN},
                      json=payload, timeout=30)
    r.raise_for_status()
    run = r.json()["data"]
    run_id = run["id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(15)
        r = requests.get(f"{API}/actor-runs/{run_id}", params={"token": TOKEN}, timeout=30)
        d = r.json()["data"]
        if d["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            if d["status"] != "SUCCEEDED":
                raise RuntimeError(f"actor {actor} run {run_id}: {d['status']}")
            return get_dataset(d["defaultDatasetId"])
    raise TimeoutError(f"actor {actor} run {run_id} not finished in {timeout}s")


def get_dataset(dataset_id):
    r = requests.get(f"{API}/datasets/{dataset_id}/items",
                     params={"token": TOKEN, "clean": "true"}, timeout=60)
    r.raise_for_status()
    return r.json()


def scrape_groups(group_urls, posts_per_group=5):
    return run_actor(GROUPS_ACTOR, {
        "startUrls": [{"url": u} for u in group_urls],
        "resultsLimit": posts_per_group,
        "onlyPostsNewerThan": "1 day",
        "viewOption": "CHRONOLOGICAL",
    })


def scrape_comments(post_urls, per_post=20):
    return run_actor(COMMENTS_ACTOR, {
        "startUrls": [{"url": u} for u in post_urls],
        "resultsLimit": per_post,
    })
