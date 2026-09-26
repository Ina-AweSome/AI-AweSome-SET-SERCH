# AI六者横断ノート

GitHub Pages 配信先（本番）: https://osamuina8008.github.io/business-tools/study/ai/

このディレクトリは `osamuina8008/business-tools` の `study/ai` をソースにした作業コピーです。本番反映は business-tools への同期が必要です。

## 頭に入る版（q.sum）

各問題 JSON の `qs[].sum` を、画面冒頭の「頭に入る版」が描画します（`index.html` の `sumBlock`）。

### 再生成

```bash
# 欠落分だけ埋める（LLM品質の既存 sum は保持）
python3 qsummary.py

# 抽出版（via=extractive）だけ作り直す
python3 qsummary.py --force

# LLM品質の sum まで上書きする場合（非推奨）
QSUM_OVERWRITE_LLM=1 python3 qsummary.py --force
```

元の定時ジョブ版 `qsummary.py` は手元 Mac で外部 LLM API を呼ぶ想定で、リポジトリには含まれていませんでした。  
ここにある `qsummary.py` は **6社解説からの抽出版**です。より高品質な要約が必要なら、手元の LLM 版パイプラインを再実行して `via` なしの `sum` で上書きしてください。
