from datetime import datetime, timedelta

import requests
from .base import BaseRetriever, register_retriever
from ..protocol import Paper
from loguru import logger
from typing import Any
from time import sleep

@register_retriever("biorxiv")
class BiorxivRetriever(BaseRetriever):
    server = "biorxiv"

    def __init__(self, config):
        super().__init__(config)
        if self.retriever_config.category is None:
            raise ValueError(f"category must be specified for {self.name}")

    def _get_collection(self, api_url: str) -> list[dict[str, Any]]:
        retry_num = 10
        delay_time = 10
        for i in range(retry_num):
            try:
                response = requests.get(api_url, timeout=30)
                response.raise_for_status()
                break
            except Exception as e:
                if i == retry_num - 1:
                    raise e
                else:
                    logger.warning(f"Failed to retrieve papers: {str(e)}. Retry in {delay_time} seconds.")
                    sleep(delay_time)
        result = response.json()
        return result['collection']

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        endpoint = f"https://api.biorxiv.org/details/{self.server}"
        lookback_days = self.config.executor.get("lookback_days")
        categories = {category.lower() for category in self.retriever_config.category}
        if lookback_days:
            start, end = self.date_window(lookback_days)
            last_day = (end - timedelta(days=1)).date()
            recent = {}
            cursor = 0
            while True:
                page = self._get_collection(f"{endpoint}/{start.date()}/{last_day}/{cursor}")
                for entry in page:
                    if entry['category'] not in categories:
                        continue
                    doi = entry['doi']
                    if doi not in recent or int(entry['version']) > int(recent[doi]['version']):
                        recent[doi] = entry
                if len(page) < 30:
                    break
                cursor += len(page)
            collection = sorted(
                recent.values(), key=lambda entry: datetime.strptime(entry['date'], '%Y-%m-%d'), reverse=True,
            )
            return collection[:10] if self.config.executor.debug else collection

        collection = self._get_collection(f"{endpoint}/2d")
        if len(collection) == 0:
            logger.warning(f"No {self.server} paper found")
            return []
        dated_collection = [
            (datetime.strptime(c['date'], "%Y-%m-%d").date(), c)
            for c in collection
        ]
        latest_date = max(date for date, _ in dated_collection)
        collection = [c for date, c in dated_collection if date == latest_date]
        collection = [c for c in collection if c['category'] in categories]
        if self.config.executor.debug:
            collection = collection[:10]
        return collection


    def convert_to_paper(self, raw_paper:dict[str, Any]) -> Paper | None:
        title = raw_paper['title']
        authors = [a.strip() for a in raw_paper['authors'].split(';')]
        abstract = raw_paper['abstract']
        pdf_url = f"https://www.{self.server}.org/content/{raw_paper['doi']}v{raw_paper['version']}.full.pdf"
        full_text = None # biorxiv forbids scraping its pdf
        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=pdf_url,
            pdf_url=pdf_url,
            full_text=full_text
        )
