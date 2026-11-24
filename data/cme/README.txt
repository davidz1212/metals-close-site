CME 交割通知 PDF 自动解析目录（data/cme/）

使用方式：
1. 用浏览器打开 CME 官方免费交割通知页面：
   https://www.cmegroup.com/clearing/operations-and-deliveries/nymex-delivery-notices.html
2. 下载当日的 MetalsIssuesAndStopsReport.pdf（里面同时包含当日交割手数与当月累计手数）。
3. 将下载的 PDF 直接拖入本目录（V:\metals-close\data\cme\）。
4. 容器后台每 30 秒自动检测本目录，发现新 PDF 后自动解析 COMEX 5000 SILVER 交割量并入库，无需重启容器。
