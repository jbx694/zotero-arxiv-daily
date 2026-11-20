from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from loguru import logger

from ..protocol import Paper
from .base import BaseRetriever, register_retriever


MAX_FEED_BYTES = 2 * 1024 * 1024


@register_retriever("cnki")
class CnkiRetriever(BaseRetriever):
    conversion_delay = 0

    def retrieve_papers(self) -> list[Paper]:
        papers = {}
        for paper in super().retrieve_papers():
            identity = (" ".join(paper.title.split()), tuple(paper.authors))
            papers.setdefault(identity, paper)
        return list(papers.values())

    def _retrieve_raw_papers(self) -> list[ElementTree.Element]:
        feed_urls = self.retriever_config.feed_urls
        if not feed_urls:
            raise ValueError("source.cnki.feed_urls must contain at least one CNKI journal RSS URL")

        lookback_days = self.config.executor.get("lookback_days") or 1
        start, end = self.date_window(lookback_days)
        debug = self.config.executor.debug
        entries = []
        for feed_url in feed_urls:
            try:
                request = Request(feed_url, headers={"User-Agent": "zotero-arxiv-daily/1.0"})
                with urlopen(request, timeout=15) as response:
                    body = response.read(MAX_FEED_BYTES + 1)
                if len(body) > MAX_FEED_BYTES:
                    raise ValueError("RSS response exceeds the size limit")
                channel = ElementTree.fromstring(body).find("channel")
                if channel is None:
                    raise ValueError("RSS channel is missing")
            except (OSError, ElementTree.ParseError, ValueError) as exc:
                logger.warning(f"Could not read CNKI RSS feed {feed_url}: {exc}")
                continue

            items = channel.findall("item")
            logger.info(f"Read {len(items)} entries from CNKI feed {channel.findtext('title', feed_url)}")
            if debug:
                entries.extend(items[:10])
                continue
            for item in items:
                try:
                    published = parsedate_to_datetime(item.findtext("pubDate", ""))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                except (ValueError, OverflowError):
                    logger.warning("Skipping CNKI article with an invalid RSS publication date")
                    continue
                if start <= published < end:
                    entries.append(item)
        return entries

    def convert_to_paper(self, raw_paper: ElementTree.Element) -> Paper | None:
        title = raw_paper.findtext("title", "").strip()
        abstract = raw_paper.findtext("description", "").strip()
        url = raw_paper.findtext("link", "").strip()
        article_link = urlsplit(url)
        if not title or not abstract or article_link.scheme != "https" or article_link.hostname != "kns.cnki.net":
            return None
        return Paper(
            source=self.name,
            title=title,
            authors=[name.strip() for name in raw_paper.findtext("author", "").split(";") if name.strip()],
            abstract=abstract,
            url=url,
        )
