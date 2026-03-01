# 常用 AMiner venue_id 速查表

从 AMiner 期刊/会议页面 URL 最后一段提取 venue_id：

```
https://www.aminer.cn/open/journal/detail/<venue_id>
```

## 硬件 / EDA 会议

| 会议名称                                                         | venue_id                   |
| ---------------------------------------------------------------- | -------------------------- |
| Design Automation Conference (DAC)                               | `5ea1c5c1edb6e7d53c00e7ad` |
| International Conference on Computer-Aided Design (ICCAD)        | `5ea1d155edb6e7d53c00fca6`  |
| International Symposium on Computer Architecture (ISCA)          | `5ea1dd51edb6e7d53c010cea` |


## AI / ML 会议

| 会议名称                                                          | venue_id |
| ----------------------------------------------------------------- | -------- |
| Neural Information Processing Systems (NeurIPS)                   | `5ea1e340edb6e7d53c011a4c`   |
| International Conference on Machine Learning (ICML)               | `5ea1d5ebedb6e7d53c0101f4`   |
| International Conference on Learning Representations (ICLR)       | `5ea1d518edb6e7d53c0100cb`   |
| AAAI Conference on Artificial Intelligence (AAAI)                 | `5ea54a70edb6e7d53c035689`   |
| IEEE Conference on Computer Vision and Pattern Recognition (CVPR) | `5eba43d8edb6e7d53c0fb8a1`   |

## 系统 / 网络会议

| 会议名称    | venue_id |
| ----------- | -------- |
| ACM SIGCOMM | 待补充   |
| USENIX OSDI | 待补充   |
| Symposium on Operating Systems Principles  (SOSP)    | `5ea1b726edb6e7d53c00ca99`   |

---

> **如何找到新的 venue_id：**
>
> 1. 在 AMiner 搜索目标会议/期刊
> 2. 进入对应的期刊/会议详情页
> 3. 复制 URL 末尾的 ID 字符串
