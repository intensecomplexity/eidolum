# Eidolum classification rules

(Repo-canonical copy — keep in sync with the prompt in
`cc_recover_classifier_errors.py` and the Google Drive copy used by
claude.ai cowork sessions.)

For each video in the batch JSON, extract stock predictions made by the
analyst. Output a JSON results file.

A valid prediction has ALL of:
- ticker symbol: a real, exchange-listed symbol from ANY market worldwide,
  OR a real cryptocurrency. Keep every genuine call regardless of country.
  Storage convention: US stocks bare (AAPL, TSLA); non-US stocks take the
  Yahoo-Finance exchange suffix — London .L (BARC.L), Toronto .TO (SHOP.TO),
  Hong Kong .HK (0700.HK), Australia .AX, Frankfurt .DE/.F, Paris .PA,
  Swiss .SW, Tokyo .T, Amsterdam .AS, India NSE .NS / BSE .BO; crypto bare
  (BTC, ETH, SOL, XRP)
- direction (bullish OR bearish)
- forward-looking language ("I think", "will", "target", "by Q3")
- source_timestamp_seconds (the second in the video where the prediction
  was made — required, drop the prediction if unknown)
- optional: target_price (number), timeframe_days (integer)

REJECT predictions that are:
- Past-tense reporting ("revenue grew 40%", "missed estimates",
  "benefited from", "was up") — history is not a prediction, even when it
  explains a mechanism that could continue
- Inferred direction: a direction derived from general sector/industry/
  mechanism talk (tariff mechanics, rate effects, commodity cycles) rather
  than the speaker explicitly making a forward call on the named ticker.
  Require an explicit call on THAT ticker — "I think X drops", "bearish
  on X", "X will...", or a price target for X. Sector/tariff mechanics
  alone is NOT a prediction.
- Ad reads ("sponsored by", "use code", "brought to you by")
- Pronoun-only context ("they're going up" without naming the company)
- Wrong-ticker attribution (ticker appears but context is about a
  different company)
- Contradictory pairs (same video bullish AND bearish on same ticker —
  drop both)
- Hallucinated / made-up tickers (must be real, e.g. NOT "MACRO",
  NOT "SPY500")

## Output format

Write to cowork_batch_NNN_results.json (matching the batch number):

{
  "batch_id": "001",
  "processed_at": "<ISO UTC>",
  "results": [
    {
      "video_id": "<11-char id>",
      "predictions": [
        {
          "ticker": "AAPL",
          "direction": "bullish",
          "target_price": 250,
          "timeframe_days": 90,
          "source_timestamp_seconds": 142,
          "context": "<verbatim quote, ~30-80 chars>",
          "confidence": 0.85
        }
      ]
    }
  ]
}

For videos with no valid predictions: include them with predictions: [].

Print "BATCH NNN DONE - X predictions across N videos" when done.
