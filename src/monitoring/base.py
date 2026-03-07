from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Activity:
    app_name: str
    window_title: str
    url_or_filename: str = ""
    chrome_profile: str = ""

class BaseObserver(ABC):
    @abstractmethod
    def get_current_activity(self) -> Activity:
        """
        Returns the current active window information.
        """
        pass
