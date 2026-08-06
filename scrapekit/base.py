from abc import ABC, abstractmethod


class BaseScraper(ABC):
    @abstractmethod
    def fetch_listings(self):
        """Return list of dicts: titre, prix, lien."""
        raise NotImplementedError
