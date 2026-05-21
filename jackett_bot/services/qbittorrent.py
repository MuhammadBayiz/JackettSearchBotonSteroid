import qbittorrentapi
import logging


class qBittorrentService:
    def __init__(self, host: str, username: str, password: str, category: str):
        self.host = host
        self.username = username
        self.password = password
        self.category = category
        self.client = qbittorrentapi.Client(
            host=self.host,
            username=self.username,
            password=self.password,
        )
        self.logger = logging.getLogger("JackettSearchBot.qBittorrentService")

    def _ensure_authenticated(self):
        try:
            self.client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            self.logger.error("Failed to login to qBittorrent: %s", e)
            raise

    def add_torrent(self, url: str, extra_tags: list[str] | None = None) -> bool:
        self._ensure_authenticated()
        try:
            tags = ["jackettsearch"]
            if extra_tags:
                tags.extend(extra_tags)

            return (
                self.client.torrents_add(
                    urls=url,
                    tags=",".join(tags),
                    category=self.category,
                )
                == "Ok."
            )
        except Exception as e:
            self.logger.error("Failed to add torrent to qBittorrent: %s", e)
            raise

    def get_torrents(
        self, tag: str = "jackettsearch"
    ) -> list[qbittorrentapi.TorrentDictionary]:
        self._ensure_authenticated()
        try:
            # We fetch torrents and sort them by added_on descending later or let API do it
            torrents = self.client.torrents_info(tag=tag, sort="added_on", reverse=True)
            return list(torrents)
        except Exception as e:
            self.logger.error("Failed to get torrents from qBittorrent: %s", e)
            raise
