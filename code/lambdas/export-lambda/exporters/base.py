from abc import ABC, abstractmethod
from utils.helpers import build_cover

class Exporter(ABC):
    """
    所有檔案格式導出的基礎類別。

    子類別必須實作 export() 方法。
    """

    def __init__(self, content_dict: dict, company_info: dict):
        self.content = content_dict
        self.company_info = company_info
        self.title, self.period, self.extra = build_cover(company_info)

    @abstractmethod
    def export(self, file_path: str):
        """
        將內容導出到指定的檔案路徑。

        Args:
            file_path (str): 要輸出的完整檔案路徑。
        """
        pass
