import os
import json
import requests
from dotenv import load_dotenv


class FacebookClient:
    def __init__(self, access_token=None, version="v19.0"):
        load_dotenv()
        self.access_token = access_token or os.getenv("FB_ACCESS_TOKEN")
        self.base_url = f"https://graph.facebook.com/{version}"

        if not self.access_token:
            raise ValueError("Access token is required")

    # -------------------------
    # Core request handler
    # -------------------------
    def _get(self, endpoint, params=None):
        if params is None:
            params = {}

        params["access_token"] = self.access_token
        url = f"{self.base_url}/{endpoint}"

        res = requests.get(url, params=params)

        if res.status_code != 200:
            raise Exception(res.json())

        return res.json()

    def _post(self, endpoint, data=None):
        if data is None:
            data = {}

        data["access_token"] = self.access_token
        url = f"{self.base_url}/{endpoint}"

        res = requests.post(url, data=data)

        if res.status_code != 200:
            raise Exception(res.json())

        return res.json()

    # -------------------------
    # User
    # -------------------------
    def get_me(self):
        return self._get("me", {
            "fields": "id,name,email"
        })

    def get_posts(self, limit=5):
        return self._get("me", {
            "fields": "id,feed{link}",
            "limit": limit
        })

    def get_all_posts(self):
        data = self.get_posts(limit=10)
        all_posts = []

        while True:
            all_posts.extend(data.get("data", []))

            paging = data.get("paging", {})
            next_url = paging.get("next")

            if not next_url:
                break

            data = requests.get(next_url).json()

        return all_posts

    def get_photos(self, limit=5):
        return self._get("me/photos", {
            "fields": "id,link,created_time",
            "limit": limit
        })

    # -------------------------
    # Pages
    # -------------------------
    def get_pages(self):
        return self._get("me/accounts")

    def get_page_posts(self, page_id):
        return self._get(f"{page_id}/posts", {
            "fields": "message,created_time"
        })

    # -------------------------
    # Engagement
    # -------------------------
    def get_comments(self, post_id):
        return self._get(f"{post_id}/comments", {
            "fields": "from,message,created_time"
        })

    def get_reactions(self, post_id):
        return self._get(f"{post_id}/reactions", {
            "summary": True
        })

    # -------------------------
    # Posting
    # -------------------------
    def create_post(self, message):
        return self._post("me/feed", {
            "message": message
        })

    # -------------------------
    # Utils
    # -------------------------
    def save_to_file(self, data, filename="data.json"):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def debug_print(self, data):
        print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    fb = FacebookClient()

    # 1. Profile
    me = fb.get_me()
    fb.debug_print(me)

    # 2. Posts
    posts = fb.get_posts()
    fb.debug_print(posts)

    # # 3. All posts
    # all_posts = fb.get_all_posts()
    # print(f"Total posts: {len(all_posts)}")

    # # 4. Save data
    # fb.save_to_file(all_posts, "posts.json")

    # 5. Pages
    # pages = fb.get_pages()
    # fb.debug_print(pages)

    # 6. If you have a post_id
    # comments = fb.get_comments("POST_ID")
    # fb.debug_print(comments)

    # 7. Create post (may be restricted)
    # fb.create_post("Hello from class-based client 🚀")