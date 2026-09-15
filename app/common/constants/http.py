"""HTTP 传输层的稳定性能参数。"""

# 只压缩足以抵消 CPU 与响应头开销的响应体。level 6 在 2 核部署规格下
# 兼顾压缩率与运行时成本；图片等已压缩格式不会命中配置的文本 MIME。
API_GZIP_MINIMUM_SIZE = 1024
API_GZIP_COMPRESSION_LEVEL = 6
