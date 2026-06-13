import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# .env 로드
load_dotenv()

class Config:
    def __init__(self):
        # API Keys
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
        self.NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
        self.NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
        self.LLM_API_KEY = os.getenv("LLM_API_KEY")
        self.LLM_API_URL = os.getenv("LLM_API_URL")
        self.LLM_MODEL = os.getenv("LLM_MODEL")

        # Other settings
        self.DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

        # Data directory configuration
        self.DATA_DIR = os.getenv("DATA_DIR", "data")
        os.makedirs(self.DATA_DIR, exist_ok=True)
        self.DB_PATH = os.path.join(self.DATA_DIR, "curato.db")

        # Load YAML Config
        self.config_data = {}
        config_path = "config.yaml"
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self.config_data = yaml.safe_load(f) or {}

    def get(self, key, default=None):
        return getattr(self, key, self.config_data.get(key, default))

    @property
    def collectors(self):
        return self.config_data.get("collectors", {"naver": True, "clien": True, "ruliweb": True})

    @property
    def naver_issue_urls(self):
        return self.config_data.get("naver_issue_urls", [])

    @property
    def indexer(self):
        return self.config_data.get("indexer", {})

    @property
    def grouper(self):
        return self.config_data.get("grouper", {})

    @property
    def ranker(self):
        return self.config_data.get("ranker", {})

    @property
    def llm(self):
        return self.config_data.get("llm", {})

config = Config()

def load_config():
    return config
