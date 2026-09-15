"""图片存储端口与适配器。"""

from app.storage.image import ImageStorage, LocalImageStorage, StoredImage

__all__ = ["ImageStorage", "LocalImageStorage", "StoredImage"]
