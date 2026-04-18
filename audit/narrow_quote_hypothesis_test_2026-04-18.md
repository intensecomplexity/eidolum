# Narrow-Quote Hypothesis Test — 2026-04-18

Claim under test: rows for NVDA, TSLA, META, AAPL, GOOGL, MSFT that land in the grounding classifier's `inferred` bucket mostly contain the company name in the ±60s transcript window around `source_timestamp_seconds`, but not in the narrow `source_verbatim_quote`. If true, the 40.8% inferred figure is inflated by narrow-quote false negatives, not real hallucinations.

- sample size: `N=30` (target 30)
- population (inferred, company-only alias map): `174` rows
- seed: `2026_04_18_narrow_quote_test`
- transcript fetch: `fetch_transcript_with_timestamps` with 0.4s inter-request delay
- window: `(stored_ts - 60, stored_ts + 60)` seconds, strict
- alias map (company-only): 
    - `NVDA`: {nvidia}
    - `TSLA`: {tesla}
    - `META`: {facebook, meta, meta platforms}
    - `AAPL`: {apple}
    - `GOOGL`: {alphabet, google}
    - `MSFT`: {microsoft}

## Results

| bucket | description | count | % |
|---|---|---:|---:|
| A | narrow-quote false negative (wide hit, narrow miss) | 21 | 70% |
| B | genuine name-absent (wide miss, narrow miss) | 8 | 26% |
| C | classifier bug (narrow hit — should be empty) | 0 | 0% |
| D | no transcript | 1 | 3% |

**Verdict:** **CONFIRMED** — narrow quote is driving the false-positive inferred rate.

## Bucket A detail (narrow-quote false negatives)

### id=612984 ticker=`GOOGL` stored_ts=969 matched=`alphabet`
`spid`: `yt_dPnYAaRJD6U_GOOGL`

**source_verbatim_quote (narrow):**
> We have a story. We have numbers. We put them together right here. I did a 10-year analysis and you can do between 1 and 20 years. Revenue growth 5, 9, and 13% over the next 10 years. I hit the analyze button. The stock's currently at 300. I have a low price of 168, a high price of 530, a middle price of 303.

**±60s window (wide):**
> rate as time goes on which is pretty rare. And for revenue double digit 12.6 11 10.7 109 10.23 growing to $600 billion in revenue in the next four years. That's a lot of revenue guys. A lot. Now before we get into stock analyzer I want you to understand guys there's a difference between investors and speculators. Everyone thinks they're investing, they lose money, though, because they're trying to pick these amazing winners. Real true great investors do the opposite. They eliminate the losers first. That's what we're doing here when we analyze a stock. What we're trying to do is say, give us the reasons to not buy to a certain element. There's always going to be reason not to buy, but right now, I'm looking at this company going, great balance sheet, great future potential. Question is, is it too expensive? That's what we're going to do here with the stock analyzer tool. We have a story. We have numbers. We put them together right here. We have to make good assumptions about the future though, guys. Don't give the roses of assumptions. This is why we have low, middle, and high assumptions here. Give conservative ones, aggressive ones, and what you think will actually happen in the middle. If you're sitting there always doing all rosy ones, you're not preparing yourself for the downside risk. This is what's truly important about stock analyzer. And guys, this is exactly why stock analyzer tool is so popular. It's used over a million times per year by our users for exactly that. It allows people to put the numbers and a story together to come up with a price that works. So, let's pull up the last time I did Alphabet or Google. I did a 10-year analysis and you can do between 1 and 20 years if you have our software. Revenue growth 5, 9, and 13% over the next 10 years. Guys, I feel like five is low. if they have this AI issue you have to work through, I think it's low. But I think 13 is really high and difficult to hit. So I'm I'm happy with this 5 9 or 13. Now if you said to me 6, 10, and 14, okay, makes sense to me. I I don't think that there's that we don't know the exact number in the future. But if

---

### id=613814 ticker=`NVDA` stored_ts=37 matched=`nvidia`
`spid`: `yt_yfe5Z1ME7uE_NVDA`

**source_verbatim_quote (narrow):**
> I've calculated a fair value for this stock at $196 with upside if it starts making sales to China according to the $50 billion in orders it signed from Chinese businesses.

**±60s window (wide):**
> A few months ago, Nvidia said that sales for its Blackwell and Vera Rubin technology could reach $500 billion. Now, it thinks the figures will be much more than that. Nvidia said demand continues to increase for its technology despite reaching astronomical levels already. Let's take a closer look at why that's the case. So investors have been skeptical in recent weeks about Nvidia's prospects and believe that Nvidia's stock has reached peak levels. I disagree and I think Nvidia has more room to run. It's trading at a forward price to earnings of 27 and I've calculated a fair value for this stock at $196 with upside if it starts making sales to China according to the $50 billion in orders it signed from Chinese businesses. Nvidia's CFO in a recent investor conference just this morning said that the demand they see continues to increase as folks are looking to enable more computing. Since the last time we spoke we talked about that $500 billion in orders. But since then we've seen new announcements, new deals and new different in terms of both focused in terms of CSP which are cloud service providers like Microsoft, Alphabet and Amazon. The model makers like OpenAI, Anthropic and others as well as many of their neo clouds like um Coreeave, Nebius and Iron looking to add more computing. So yes, more has occurred. And remember when Nvidia gave this $500

---

### id=611881 ticker=`NVDA` stored_ts=2134 matched=`nvidia`
`spid`: `yt_C4Ct44LHZm0_NVDA`

**source_verbatim_quote (narrow):**
> I would argue that over a $4 trillion market cap isn't going to be able to grow at 80% a year for the next five years. It's just not going to be able to do that. I would bet my career on it.

**±60s window (wide):**
> times before? I think you get the picture. Now, moving to Nvidia. Nvidia, if I look at this stock historically prior to the AI developments, if you will, this was a good company with good growth, but it was also pretty volatile and it also tracked its earnings growth very well. Now, we've had this huge surge in earnings and the stock price has followed that. Okay. But if I'm looking at the future once again, analysts are expecting 29% growth. That would give us a decent rate of return if it traded at that multiple. If it traded at the current multiple, of course, that would give us a 29% rate of return. These calculators help you think your investments through. What is my risk? What is my upside? What is my downside? What can I do investing in these stocks? Now, this is a hot stock. It's performed very well. We do have good growth going forward. If we look at historical growth, the stock looks like a absolute steal. But I would argue that over a $4 trillion market cap isn't going to be able to grow at 80% a year for the next five years. It's just not going to be able to do that. I would bet my career on it. Now, they can grow very fast. There could be an argument made for 29% growth, which is still extraordinary growth. I want you to understand that's extraordinary growth for a company this big and the risk of achieving that we've already seen Oracle rise 40% or 35% in one day because they're start into the game. There's a lot of companies avo micro computer. There's a lot of AI players out there now. Invit certainly one of the best not the only one. Now let's look at at Tesla here. And I think that's my last one. Let me be sure. Yeah, Tesla's the 10th stock on the list and again it's a major player, but let's look at Tesla as an investment. We did see some strong we saw no earnings growth for all these years. We saw negative earnings for much of these years all the way through 18. So, if I

---

### id=608868 ticker=`MSFT` stored_ts=197 matched=`microsoft`
`spid`: `yt_3S7PIbrW1MU_MSFT`

**source_verbatim_quote (narrow):**
> I know that long-term there is no doubt in my mind that these are stocks that will break new record highs in the future.

**±60s window (wide):**
> like a once in a decade type of opportunity. In fact, if we actually pull up their 10-year chart, well, we can see that it's pretty much the biggest drop that, you know, we've experienced, losing around 30% of their entire value from the top. And if you think I'm being overly dramatic here about this, uh, just zoom out to an all-time chart, and you can see how insanely rare it is to have anything close to a giant drop like this. I mean, it almost never happens. And by the way, whenever it does happen, when has it not been an amazing buying opportunity? Like if there's only a handful of stocks that I would say, you know, I can always buy these on the dip without having to really think much about it, it would probably be Microsoft, Amazon, and Google. And that's about it. Those three stocks, if you ever tell me that any of them are currently down over 30% of their value, I don't even need you to say another word. I barely have to think about it. I would just automatically hit the buy button on it very fast because I know that long-term there is no doubt in my mind that these are stocks that will break new record highs in the future. Now, sure, you could absolutely argue that the stock will sink further from here. I'm not a fortune teller. I don't claim to be one. So, I can't predict how the market will react here in the short term, even if I strongly disagree with what's going on. And there's no telling how long a specific downturn like this can last either, where everyone is panicking about AI spending and business disruptions and everything else. Uh but if there is one company that should not at all be concerning you about those two specific issues when it comes to AI and that can easily recover from these from the dip long term, it is absolutely Microsoft. I mean this is a company that generates bigger financials than most other countries in the world. Like forget about is this you know one of the best companies to own. This is like one of the best countries to own essentially. Last year alone, for example, they did over 280 billion in revenue, which was still up 15% year-over-year with over a 100 billion

---

### id=614887 ticker=`NVDA` stored_ts=37 matched=`nvidia`
`spid`: `yt_1_k-7L2A7pQ_NVDA`

**source_verbatim_quote (narrow):**
> Can we get to $300? Can this be the greatest beat of any company ever in the world when expectations are so high? We're going to the moon. At least hopefully.

**±60s window (wide):**
> All right. All right. All right. Oh, here we go. Nvidia earnings day. Oh, snap. It's going to be crazy. Nvidia earnings. Nobody knows Nvidia earnings better than we do. Well, folks, welcome back. Uh, it's another one of those earnings days. Yes. Yes. It's one of those days where everybody's been waiting for the data. Mostly because we can't get data out of the White House cuz they don't want to show us how bad things actually are. And instead now we're all going to hang our hats on Nvidia. Can we get to $300? Can this be the greatest beat of any company ever in the world when expectations are so high? Now, in fairness, we've come off some all-time highs here already for Nvidia. So, you know, who knows? Maybe we have to be uh a little modest with our expectations, but nah, screw that. It's Nvidia. We're going to the moon. At least hopefully. Obviously, expectations really, really high for Nvidia. uh not just the uh demand coming from what 40% of their demand coming from Microsoft, Facebook, Meta, Google, but the demand coming from all the uh data center developers, iron, nbby, coreweave, super micro to some extent, even though they've got >> little PP, >> we've got a 30% chance of rate cuts. So, we can't bet on rate cuts to keep this market booming, which means we're going to have to rely on Nvidia. Will Nvidia save the day? That's going to be the

---

### id=606614 ticker=`TSLA` stored_ts=688 matched=`tesla`
`spid`: `yt_Rv3Cqo5Wty0_TSLA`

**source_verbatim_quote (narrow):**
> they gave Outlook expecting 20 to 30% vehicle sales growth in 2025 and they're expecting the new Cyber cab they launch to reach volume production in fiscal 2026

**±60s window (wide):**
> they can kind of predict it with the automotive business and the energy generation business but a lot of that self-driving taxi Network and eventually the autonomous robot that's very unknown right now in the last quarter they did have record deliveries for vehicles and they Remain the only profitable electric vehicle company this has actually been a big competitive Advantage for them as they can continue to lower cost they have 19.84% gross margins as of the latest quarter with 10.7% operating margins and 8.61% net margins and in the automotive space those are great margins their energy storage business is also growing massively albe in terms of Revenue it's a much smaller part of the p right now and this quarter is actually very good financially they had $6.3 billion of operating cash flow and they're reinvesting massively a lot of which is going into new AI data centers so that they can train their self-driving models where they have a massive Advantage they spent $3.5 billion in the latest quarter on Capital expenditures and going into fiscal 2025 they're actually set up really well for growth in the coming years they gave Outlook expecting 20 to 30% vehicle sales growth in 2025 and they're expecting the new Cyber cab they launch to reach volume production in fiscal 2026 they also announced that they're planning to launch more affordable models in the first half of 2025 that's likely how they get to that high vehicle growth rate they also just recently launched a new model y this follows last year's refresh of the model 3 and if you're analyzing tested stock the model 3 and model y are the main products the model Y is actually the bestselling car in the world so refresh of that vehicle is likely another way they get to that new new increase in sales but as many of you know Tesla trades at a very high valuation so they need massive growth in the future in order for this to make sense luckily they are leaders in multiple high growth categories over the coming decades but there are a lot of unknowns so I would expect volatility especially around earnings reports like we're going to have this week for stock number five I have Microsoft toer symbol msft this was reporting Wednesday after market closed last quarter they beat on both revenue and earnings per share with a 1.67% beat on revenue and 6 . 45% on

---

### id=608254 ticker=`GOOGL` stored_ts=50 matched=`google`
`spid`: `yt_w9Z-lIWLUUk_GOOGL`

**source_verbatim_quote (narrow):**
> And I'm sorry guys, but anytime you get one of these extremely rare dips on what is what I feel actually the best overall stock in the entire world right now, you got to be ready to pounce on that.

**±60s window (wide):**
> Welcome back subscribers to my world of stocks. In today's video, we're diving deep into three very powerful AI stocks that are currently going through some huge dips down around 20 to 50% of their values, and I'll explain why they're falling, what makes them special in the AI arena, and why now may actually be a great time to pounce on them for their long-term potential. So, please subscribe if you haven't already. Hit that like button if you enjoy the video. Let's go ahead and jump straight into this. All right. Now, first up here, I'm going with the king of search in Google, who actually just fell another 7% in a single day this week on new search fears that I'll explain in just a second. But this also leaves them down over a quarter of their value from the top. And I'm sorry guys, but anytime you get one of these extremely rare dips on what is what I feel actually the best overall stock in the entire world right now, you got to be ready to pounce on that. Now, why has the stock been falling? Well, the most recent dip this week had to do with Apple reportedly working on their own AI powered search engine for the Safari browser, which has always been using Google by default. Same goes for their various devices. But the thing is that Google has always paid billions of dollars for that prime search placement on iPhones. So if Apple was to all of a sudden launch their own AI search or even teams up with another provider instead, well then the fear is that a large chunk of Google's traffic and ad revenue could be at risk. All the meanwhile, other AI chat bots like OpenAI's chat GPT have also proven to be reliable new ways of getting information when in the past most people would just, you know, simply rely on Google alone. Again, these are major concerns. But the

---

### id=608832 ticker=`NVDA` stored_ts=1187 matched=`nvidia`
`spid`: `yt_Azk05W9GK64_NVDA`

**source_verbatim_quote (narrow):**
> So, taking a look at it here, I'll refresh the page just in case that makes any difference. But Google stock. So again, during trading hours it was down about 2%. After hours it's actually up, you know, 2.5%. So it kind of balances out. It's probably going to have end up having a flat day even though it there was some major turbulence early on, but it might just kind of finish flat.

**±60s window (wide):**
> why free cash flow as a growth rate it actually declined in the quarter. it went down by 1%. So, it's affecting their free cash flow. And for the for the full year, it was about flat. So, that again is the concern here that how how much are they spending? Again, I think it's justified because I don't really care. I like I don't really care if if they're not making a giant net profit because of how much they're investing. I they're already so large. They're already so dominant. I'm not really worried about that. I actually want them to invest that money. What else are they going to do with it? They don't pay huge dividends. They I mean, yeah, you could buy back stock, but you could do that later. The market is at at record highs. Google stock is at record highs. I think right now, invest the money. Invest money back into the business. Make yourself stronger for the future, for the long term, because as a long-term investor, that's what I mostly care about myself. So, anyway, I think that'll just about wrap it up here for the video. We'll just take one quick look at the stock again just to see how it's doing. But, so, taking a look at it here, I'll refresh the page just in case that makes any difference. But Google stock. So again, during trading hours it was down about 2%. After hours it's actually up, you know, 2.5%. So it kind of balances out. It's probably going to have end up having a flat day even though it there was some major turbulence early on, but it might just kind of finish flat. Now I believe Amazon reports tomorrow. I want to say they report tomorrow. We have still have some bigger earnings reports coming up later in the month like um what else is there? Nvidia. So there is some stuff still coming up that could affect obviously the market but Google was for sure the big one to look at today and just a little bit of a non-reaction. I think it's just you had the combination of phenomenal performance business-wise but incredible spending capex-wise and that's why the stock is like flat,

---

### id=609415 ticker=`AAPL` stored_ts=909 matched=`apple`
`spid`: `yt_CRKqAg9YKHo_AAPL`

**source_verbatim_quote (narrow):**
> if we jump over to our stock analysis sheet come down here and look at them from a discounted cash flow perspective we can see assuming a free cash flow growth rate of about 10% which I'm not sure if they'll achieve we come to an intrinsic value of about $191 189 now to be fair that's only about 12% off from the current share price and they probably do warant a multiple

**±60s window (wide):**
> look at earnings projections for this company we can see we're talking about high single digits to around 12 to 10% now if we start to look at Apple from a valuation perspective let's go ahead and start by looking at the free cash flow analysis here's what we can see the free cash flow yell for Apple right now is sitting at about 3.02% while the 10 your average is sitting at 6.1% again free cash flow yield this is saying if we invested $100 into the stock how much free cash flow would the stock generate and right now it's about $3 but historically speaking it's about $610 that's a pretty big difference in the historical valuation compared to right now if we look at the price to free cash flow valuation again apple looks considerably more expensive than how it's traded over the past decade and the same thing is true if we look at EV to free cash flow and then with all that being said we can also see free cash flow growth has slown down the 10-e free cash flow kager is about 8.1 the 5year looks decent at 13% but the last 3 years sitting at about 5.39% now if we jump over to our stock analysis sheet come down here and look at them from a discounted cash flow perspective we can see assuming a free cash flow growth rate of about 10% which I'm not sure if they'll achieve we come to an intrinsic value of about $191 189 now to be fair that's only about 12% off from the current share price and they probably do warant a multiple now if we look at the Historical multiple valuation again we can see trolling 12 months PE ratio is about 34 while the average over the last decade significantly lower at about 20.7 to so when we talk about the run up and share price that Apple's seen over the last year we have to keep in mind Apple has not been growing its earnings over the last four years so any gains in share price that Apple's really been seeing over the last four to 5 years is simply due to the fact that people are willing to pay more for the stock it's all po expansion the earnings haven't grown but the share price has been growing that's something I don't typically like to see now again complete transparency like always apple is my portfolio but I

---

### id=615098 ticker=`META` stored_ts=1640 matched=`META`
`spid`: `yt_v7Arp52edIg_META`

**source_verbatim_quote (narrow):**
> if you want the masses to really buy a product like the Metag Glasses instead of just like, you know, people that are kind of really forward looking on technology, you need killer apps. And I'm like stuff like that big time. That's how you capture new platforms but you need killer apps if you're really going to have something take off.

**±60s window (wide):**
> right? Here's the deal. The iPhone took off for one core reason. It had a killer app. The killer app was the internet, right? And Safari. Prior to that, cell phones were were already loved and never didn't really need any tweaking. People loved the text conversations you had. They loved their Blackberry devices. They loved the ability to call. Uh they loved that they would have an iPod as well that they could listen to music with. There was no issue with the phone that made everybody say, "I hate phones." Like I don't remember being in high school and everybody saying, "I hate phones. I can't wait till a new phone comes out." No, no, no. Everybody loved their phones. People had the sidekicks. Anybody remember the sidekick phones? For some of you young, you're probably like, "What the heck? Is he speaking a foreign language right now?" Remember the Sidekicks, man? The Blackberries, like all those devices were like great in their day. But then iPhone came out. And the thing that really made people say, "I got to go get this iPhone." Was the fact that it had a good internet browser. And that did not exist prior to iPhone. The internet experience was complete trash on any of those old devices. But then iPhone came out and said, "We got this great internet." And people are like, "Oh my gosh, like this is basically like using internet on a laptop or a computer, but it's on my phone. Sign me up." And so that's what we're talking about. If you want the masses to really buy a product like the Metag Glasses instead of just like, you know, people that are kind of really forward looking on technology, you need killer apps. unique things that makes people say this is so awesome. This is way better than like if I didn't have this device. It makes my life way easier and better. Boom. That's how you get the masses to adopt. And then if you're meta, that's how when you just keep building on it, building on it, building on it, and next thing you know, maybe you have the replacement of the phone, right? I know as of today it's very hard for us to even imagine a replacement of our smartphones today but you know don't be surprised if that gets replaced in 10 20 years right there's a lot of devices and things that we've had over time that we could never imagine that being replaced until a new

---

### id=615657 ticker=`NVDA` stored_ts=45 matched=`nvidia`
`spid`: `yt_adE5cOZNNJc_NVDA`

**source_verbatim_quote (narrow):**
> If we break below here, I think what's likely is, you know, the most bullish thing it can do is actually dip below there for a day or two and then come back up and then you could see this thing really launch.

**±60s window (wide):**
> semiconductors. This is the first losing day in, you know, a little while here. I think six or seven days. And it's still in a giant uptrend. This, look how far we are away from the 20-day moving average. We're clearly stretched, but it doesn't mean, you know, up too much doesn't mean there might not still be buyers. Breaking this little low from yesterday says, you know, maybe we just get a little bit more cautious and, you know, if we start to monitor how a pullback would develop. Now, people were talking, of course, about Nvidia as well, and I thought it had the possibility that if it broke below here that it would continue down to uh the 5day moving average, and that's exactly where we are right now. This is going to be a key level and a widely watched level. If we break below here, I think what's likely is, you know, the most bullish thing it can do is actually dip below there for a day or two and then come back up and then you could see this thing really launch. So, I would, you know, be aware of, you know, protecting your gains in here. Um, and if it breaks down below there, I wouldn't necessarily get bearish because we've got 20 and 50-day moving average in a company with some of the best fundamentals, I'm told, on the planet. Um, so keep an eye on a little bit of profit taking. That's that's all you can look at in terms of that.

---

### id=614029 ticker=`AAPL` stored_ts=1123 matched=`apple`
`spid`: `yt_N2e_N1nBlvA_AAPL`

**source_verbatim_quote (narrow):**
> it looks like we're on a destiny maybe back to retest areas up here at 180 190 but there's nothing about any of this including the company's financials

**±60s window (wide):**
> you should be able to capitalize from it now meta gap down after earnings have drifted back to a level of resistance it'll be decision time for meta next week can you power up above 450 if you do you got areas up at 480 which which is probably the next stop if you get rejected here in meta get your wallet ready because that's your opportunity you get rejected here we could retest this area at 420 that could be interesting lower anything south of 420 and uh yeah you're probably smoking and you're buying a little bit of meta at the same time although partake in that first part now speaking of gaps on the chart look at Apple we were cons we're still consolidating sideways so let's get something real yes we put up a big gap in the chart that canceled out kind of the micro downtrend that we were making we were making lower highs lower lows we thought there was a potential to break down here to the 150 range at least temporarily that's absolutely not going to happen it looks like we're on a destiny maybe back to retest areas up here at 180 190 but there's nothing about any of this including the company's financials especially fundamentally there's nothing that says to me with apple that they're going to break out above $190 per share other than that the company is using their cash on hand and operating cash flows to buy back the share so that potentially could be enough to push the shares to all-time Highs but do is that what I want do I want to sell into that I think that's the question Apple shareholders have to have do you want to be a buyer along with apple or do you want to sell your shares to Apple considering device sales and really everything across the board fundamentally actually doesn't really look very good for Apple now moving on to Amazon just beautiful I mean this is all you need to see with Amazon beautiful technical pattern we are M marching our way back to the top it looks like we we're trying to push through it's difficult you're trying to push through this 180 level if Amazon is

---

### id=609470 ticker=`GOOGL` stored_ts=321 matched=`google`
`spid`: `yt_8asEVm_XsSs_GOOGL`

**source_verbatim_quote (narrow):**
> Now, based on the average analyst estimate 2029 earnings per share is projected to be $15.57. Now, in order to get our price target estimate, we have to project a 2029 PE ratio. And again, I prefer to be conservative with my projections. We can see the 4-year average PE ratio for this company is about 23.02 and the current PE ratio is a good bit lower at 20.38. Let's assume that that PE ratio doesn't recover and stays around where it's at right now. So, we'll come over here and plug in 20.5. And what we can see with 2029 earnings per share at $1557 and a 2029 PE ratio of 20.5, this would give them a price target of $31,910 by 2029, leading to a 95% total return target.

**±60s window (wide):**
> huge boost of confidence. And it's almost like sentiment around the stock changed overnight. On top of this, we have to remember Google is a major player in the AI race themselves. If we look at the AI leaderboards, we can see Gemini, which is Google's AI, is a major player. For example, if we look at best overall, Gemini is barely behind chat GPT's open AI. If we look at best in adaptive reasoning, we can see Gemini 2.5 Pro is number one. Come up here. If we go ahead and look at best in reasoning, we can see Gemini comes in at a very close second. In fact, I had a conversation with a software developer just the other day and he let me know that his organization is actually switching to using Gemini to help with their software development. So, yes, the AI race is a threat to Google, but Google's still a major player in this AI race. They saw beats on top and bottom lines, and on top of this, we still see that Google search revenue is growing at a doubledigit rate. So, let's talk about the price target for a moment. Again, what we can see is that current price is $163.83 83 and based on the average analyst estimate 2029 earnings per share is projected to be $15.57. Now, in order to get our price target estimate, we have to project a 2029 PE ratio. And again, I prefer to be conservative with my projections. We can see the 4-year average PE ratio for this company is about 23.02 and the current PE ratio is a good bit lower at 20.38. Let's assume that that PE ratio doesn't recover and stays around where it's at right now. So, we'll come over here and plug in 20.5. And what we can see with 2029 earnings per share at $1557 and a 2029 PE ratio of 20.5, this would give them a price target of $31,910 by 2029, leading to a 95% total return target. In other words, a compounded annual growth rate of 14.26%, which I would say is probably likely to outperform the market. Now, keep in mind, yes, this one's not technically quite at a 100x return, but just as of last week, we can see this company was trading as low as about $148 to $149 per

---

### id=605978 ticker=`META` stored_ts=22 matched=`facebook`
`spid`: `yt_qB3LH78ro6U_META`

**source_verbatim_quote (narrow):**
> i don't think one needs to even understand what they would do with reality labs and all of that i think make a simple bet to double your money in two or three years

**±60s window (wide):**
> facebook stock has been absolutely plummeting and is down over 31 year-to-date many popular investors who proclaim to be value investors are taking this opportunity to load up on facebook stock while it's trading at such low valuations one investor who recently had a rather interesting take on metastock is monish pibrai current valuation is very compelling i don't think one needs to even understand what they would do with reality labs and all of that i think make a simple bet to double your money in two or three years i think that's a that's a pretty low risk bet there's no guarantees in this world but i think there's a good chance you can get a double in two or three years or less and then in the meantime you get the popcorn watch the movie put a lot of butter in the popcorn and if there's things starting to pop you can say okay i'll stay on for two three more years and see if i can get another doubt saying that facebook stock could double is a pretty large claim but to find out if it's a fair statement we're going to jump into my stock valuation spreadsheet if you'd like to be able to download this spreadsheet then you can head over to my patreon page at the link in the description okay so we are currently looking at my stock valuation spreadsheet in google sheets and on this spreadsheet we have four different valuation models we have graham's valuation a discounted cash flow model a multiples valuation a dividend discount model and this will all roll into our output tab so let's go ahead and jump into our stock screener and we'll make this a 365 day chart and

---

### id=606801 ticker=`TSLA` stored_ts=1076 matched=`tesla`
`spid`: `yt_VHbjp0U5WhY_TSLA`

**source_verbatim_quote (narrow):**
> however it's already my second biggest stock and there's still up over a hundred percent this year so I'm kind of just holding it for now

**±60s window (wide):**
> security stock in Palo Alto networks also fell this month by about 13 and while I don't own it myself I do actually prefer them over Fortinet with the cheaper PEG ratio that is also cheaper than the sector as well and I'll just finish up here by scrolling a little further down at T stock fell over 10 but I prefer Verizon who is actually on the list too at just under a 10 drop and they have a mouth-watering dividend right now excuse me that has risen to the highest level I've ever seen at above an eight percent yield it is high risk but man that dividend is just so tempting that I've been buying some of the stock myself in small amounts and then finally Tesla also sank about eight percent this month because of a drop in their margins but I feel that that's really just a temporary issue they were doing a lot of sales and stuff and actually think earnings were very strong with over 40 percent gain on sales and 20 in profits however it's already my second biggest stock and there's still up over a hundred percent this year so I'm kind of just holding it for now I think I'll stop here though for the sake of time I try to keep these videos within 15 minutes and we always go over so I apologize for that but regardless I hope that you enjoyed the video thank you so much for stopping by please support the channel you can do that either on patreon or just by hitting that like button subscribing to the Channel all those things really help me out a lot help keep this channel alive and it means a lot to me guys so thank you for all that support but I will catch you in the next video my friends drop your comments down below let me know how you feel about anything we talked about hope you're all doing well take care bye-bye [Music] foreign [Music]

---

### id=609241 ticker=`AAPL` stored_ts=596 matched=`apple`
`spid`: `yt_KesKZs3p480_AAPL`

**source_verbatim_quote (narrow):**
> Ultimately, that gives us a buy price here of $226.16 with a forward PE of 29.8 with a 20% margin of safety. That's a buy price of $180.93 and a forward PE of 23.8.

**±60s window (wide):**
> averages. And given their growth over the last few years, a lot of people think that these PE ratios are certainly not justified. the market on a reverse DCF basis is giving Apple 7% free cash flow growth over the next 10 years to get to that share price. Whereas I'm actually giving them 8.6% on my big case for free cash flow growth. I do think that my growth rates for revenue are fairly conservative. I have 4.63% growth on the bare case up to 7.41% on the bull case. And for free cash flow margin, I have that at 31.97% on the bare case, up to 39.16% on the bull case. That gives us a discounted cash flow price for the bear at $182.25, $223.37 on the base case, and $2749 for the bull case. The exit multiple sits at $226.70. The comps I'm using for Apple are Google, Microsoft, and Netflix. Remember, Apple does have Apple TV. So, ultimately, that gives us a buy price here of $226.16 with a forward PE of 29.8 with a 20% margin of safety. That's a buy price of $180.93 and a forward PE of 23.8. I used to have a 10% margin of safety for Apple, but I don't think their growth really justifies it anymore. and you would need a fairly large margin of safety in order to get real growth in your investment out of this business. However, if Apple does execute and they figure out AI and they catch up to the rest of the pack and big tech, there is a lot of upside. The bullcase does have an upside here of 27.5%. But I would certainly wait on Apple if I was to buy more. I would want to see it come down below 180 into the 170s, maybe even 160s if you're feeling really riskaverse. And in fact, I do plan on selling Apple over the next couple months here to further consolidate my portfolio. Amazon is certainly having one of the worst days post earnings of

---

### id=610574 ticker=`NVDA` stored_ts=372 matched=`nvidia`
`spid`: `yt_C8w7zf3BtdQ_NVDA`

**source_verbatim_quote (narrow):**
> right now it's kind of just going sideways it's kind of teetering right on that overbought area and you can see the last time it did that it just dipped below into the sweet spot in the negative direction just and it's just consolidated sideways so i expect that it's going to probably do that again unless we get some kind of shift in the overall market

**±60s window (wide):**
> 489 billion yeah so guys and look at the look at that and look at the uh look at the p e 90 p e it makes sense that the stock's going to fall significantly in value to justify normal pe now what we're going to do though is we're going to go look at the stock analyzer tool once mo is done because the stock analyzer tool that's part of our software will allow you to make assumptions on growth rates profit margins free cash flow pe and tell you what you should pay for the stock based on your desired annualized return okay so while moe's doing that i'm going to set up the stock analyzer tool mo let's go over and see if people are trading nvidia in the beautiful bid nasa nation you know i love those bid and askers so nvidia nvidia's one that the bid nest nation has been on for a long time so they got this thing back in march right when it came up through the sweet spot and people caught this entire run which is awesome kind of settled down here for a little bit and then it did a little sweet spot reversal and we had people catch this entire run up it was it was it was incredible i think it was one of the best trades that um people in the bid and ask nation have made now right now it's kind of just going sideways it's kind of teetering right on that overbought area and you can see the last time it did that it just dipped below into the sweet spot in the negative direction just and it's just consolidated sideways so i expect that it's going to probably do that again unless we get some kind of shift in the overall market the thing i want to point out go on they did a four to one split on july 20th and july 20th is about right here and typically when the splits to me are kind of for the psychology and you would think that the volume would increase because people were because technically it's a cheaper purchase price and look at the volume over that time it's actually declined and we're sitting right at the 25 day moving average now so the split didn't go as i assume plan for the company but um yeah just keep a watch on it keep a watch on this thing if it goes and makes new all-time highs you can go for it i think this will eventually be a good swing trade this is a great stock to day trade though because the volatility is there so paul we're now going to use our stock analyzer tool this is a part of the software you get at being a patron and when we move off patreon here in the next month or so you can get access to

---

### id=613852 ticker=`GOOGL` stored_ts=97 matched=`alphabet`
`spid`: `yt_MTf2pSEkct0_GOOGL`

**source_verbatim_quote (narrow):**
> Revenue coming in at $84.7 billion that beat Expectations by about $450 million. I think everything that we'll see in today's report gives us full confidence for the Q3 coming in at over $85 billion in Revenue maybe closer to this high-end 86 87 billion worth of Revenue.

**±60s window (wide):**
> through all of the net income and we'll look at the balance sheet which after not having to spend $23 billion on a cyber security firm probably going to look pretty good and we'll look at the cash flow statement as well given how much this company is investing in Ai and other Technologies how much did they spend in the most recent quarter on those Investments and then we'll come over and look at this technically as this stock has been on a rocket ship over the last year can it continue to move higher we'll discuss that and more on today's show what is going on investors hopefully you guys are doing well out there time to talk about alphabet Inc otherwise known as Google the company announced their Q2 numbers after the battle Revenue coming in at $ 84.7 billion that beat Expectations by about $450 million Wall Street estimates were closer to 84.3 billion the highend though was 85.5 so coming underneath that I think everything that we'll see in today's report gives us full confidence for the Q3 coming in at over $85 billion in Revenue maybe closer to this high-end 8687 billion worth of Revenue certainly gives us confidence going into Q4 election season holiday shopping in Q4 should be a good ad turnout as it relates to Google we'll get to the rest of the numbers here in a moment but news crossed just today that cyber security startup whiz was walking through a $23 billion acquisition deal from Google could this turn into to be a $23 billion Mistake by this company as they say they're going to pursue a public offering probably either maybe later this year or into next year as this company has about $1 billion in annual recurring Revenue could also have to do with crowd strike struggles and potentially maybe new business walking through the door over at whiz I tell you what when we get to the balance sheet over at Google they've got a mountain of

---

### id=608862 ticker=`NVDA` stored_ts=497 matched=`nvidia`
`spid`: `yt_Wh0xvOzJWRg_NVDA`

**source_verbatim_quote (narrow):**
> So for a single chips company to be as dominant as they are with as much market share as they hold and with all of the future potential that still lies ahead to be this strongly profitable with still a valuation that is you know technically cheaper than the sector on a PG basis that's a pretty compelling story for the long term.

**±60s window (wide):**
> adjacent markets too that involve both the combination of the chips hardware as well as the robust software platforms to power many of these new and high growth technologies. And that combination has helped them dominate several different markets. In autonomous driving, for example, 20 of the top 30 EV makers, seven of the top 10 truck makers and eight of the top 10 robo taxi makers all use Nvidia. In gaming, Nvidia GPUs make up all of the top 15 most popular on Steam. In graphical work for designers, creators, and workstations, they hold 95% market share. And while I don't have exact figures for these next few, I can tell you that almost no one challenges Nvidia here either when it comes to things like smart cities. uh the metaverse, what Nvidia also refers to as the omniverse that's completely transforming industrial work. There's robotics, engineering, analytics, genomics, and more. Even some new work in quantum computing that's showing a ton of promise, too. >> [clears throat] >> So for a single chips company to be as dominant as they are with as much market share as they hold and with all of the future potential that still lies ahead to be this strongly profitable with still a valuation that is you know technically cheaper than the sector on a PG basis that's a pretty compelling story for the long term. Now whether it's a stock worth investing in it, you know, for your own portfolio, that's going to ultimately be your own decision to make based on your own extensive research and analysis. But I hope that these five key points about Nvidia helped you in any way to at least be better informed about both the company and the stock, as well as giving you maybe a few things to look out for when they report earnings very soon. But either way, I just wish you guys the best of luck out there with any decisions you make. And I'll of course be here helping you out as much as I can along the way. So, I hope you're all doing well and uh I will catch you guys in the next one. Thanks again, my friends. Take care. Bye-bye.

---

### id=607344 ticker=`META` stored_ts=368 matched=`META`
`spid`: `yt_sMFb8ofj0DQ_META`

**source_verbatim_quote (narrow):**
> Wall Street analysts have a consensus price target of $882. That implies the stock is 49% undervalued.

**±60s window (wide):**
> in all the big tech companies which are going heavy in AI. whether it's Meta, Google, Microsoft, Oracle, this ramped up to $18.8 billion in the latest quarter and over the trailing 12 months is $62.7 billion. And we're really in a cycle ramping up right now. Based on their outlook, they're expecting that to grow. Now, luckily, Meta has a fantastic high margin business that's very profitable, but this is hurting their free cash flow growth. As you can see, we are actually trending down over the trailing 12 months for the past 3 quarters. Now, as I said that they are still generating over 11 billion of free cash flow in the latest quarter. So, when we talk about Meta, you're analyzing that riskreward. Are they going to get a good return on that investment? Now, luckily, the stock price being lower gives you much more cushion to the downside. Right now, based on the 4P ratio for Meta stock, we are trading towards the lower end of its historic range. Aside from that fall 2022, early 2023 area where Meta was a screaming buy and I think Meta looks attractive here right now. Wall Street analysts have a consensus price target of $882. That implies the stock is 49% undervalued. The lowest price target on Wall Street is actually $810, which is significantly above the current price of $589. Also, another factor I think you got to consider here is that this is still a founder company. Mark Zuckerberg is highly involved and he's pivoting and going allin on AI. There was a lot of talent acquisitions earlier this year, a lot of money put into data center infrastructure, which is yet to really be seen. So, we're still kind of in that before period of uncertainty before we actually see the results of any of this. So, that could be a potential buying window. Stock number two I'm going to share today is a less speculative one. That's Visa, ticker symbol V. They are down 12.95% from their 52- week high and down 6.7% over the past month. Visa is an extremely high quality company that that rarely ever sees a significant sell-off. They have a dominant market position backed by network effects. So much so that Visa and Mastercard, they're kind of considered a duopoly. As you can see, they have a long history of earnings per

---

### id=607745 ticker=`TSLA` stored_ts=179 matched=`tesla`
`spid`: `yt_HlUYUy0dM3g_TSLA`

**source_verbatim_quote (narrow):**
> we we expect to be in production with the the Cyber cap that which is really um highly optimized for autonomous transport uh in probably well I tend to be a little optimistic with time frames um but but in in in 2026 so yeah before 2027 let me put it that way

**±60s window (wide):**
> uh they where they can actually sort of manage a fleet of cars and like a sort of manage I don't know 10 20 cars and just sort of you know take care of them like a like a Shepherd uh tends their flock you have a little your flock of cars and you're the shepherd and you take care of your flock of cars I think that would be pretty cool obviously that would be pretty sweet if they can get that price under 30,000 I don't know if they will or won't musk does tend to overpromise at times but I think at that price it would be very compelling of course all Teslas will be capable of these functionalities though and up next Elon spoke about a possible release window time frame we we do expect actually to to start uh fully autonomous unsupervised FSD uh in Texas and California next year and that that's obviously that's with the model 3 and model Y and then we we we expect to be in production with the the Cyber cap that which is really um highly optimized for autonomous transport uh in probably well I tend to be a little optimistic with time frames um but but in in in 2026 so yeah before 2027 let me put it that way again like I said Elon does tend to overpromise on a lot of stuff specifically delivery dates too so the fact that he was kind of laughing here while he said before 2027 makes me think that this thing is at least two years out and hopefully it's not too much later than that because Tesla as a company could really use some new products to drive growth for them as soon as possible anyway from there musk talked about how they have millions of vehicles out on the road collecting data and because of those millions of experiences that regular people might not have they're just going to be a lot

---

## Bucket B detail (genuine name-absent rows)

### id=612983 ticker=`NVDA` stored_ts=1410
`spid`: `yt_6_Ll8wL4g9s_NVDA`

**source_verbatim_quote (narrow):**
> Based on free cash flow, I have a low price of 78, high price of 493, middle price of 150. So based on a discounted cash flow model, your return is going to be 6.8% to 8% per year over the next 10 years.

**±60s window (wide):**
> going on. But I'm putting the 9% return in to assume everything is fine. What is the company worth? Guys, I have felt that panic in my gut as well. When stocks fall, fear takes over. You start thinking, do I sell before it gets worse? I've been there. I've made those emotional decisions and I paid heavily for them. But patience and planning are what separates principal-driven investors from degenerate gamblers. Once you understand value and how to determine it, your perspective completely transforms. Price drops become golden opportunities, not disasters. That's what we teach everything money. How to think long-term and stay calm when other investors start losing their minds and they dig holes that kneecap their financial future. Get access to the tools and the knowledge that protect your portfolio and your future from those emotional decisions that will destroy wealth. Start your 7-day trial right now. So guys, with these assumptions, I hit the analyze button. I scroll down. So based on free cash flow, I have a low price of 78, high price of 493, middle price of 150. So guys, what this is saying is if the middle assumptions all occur based on a discounted cash flow model, your return is going to be 6.8% 8% per year over the next 10 years. Is that reasonable for you? Great company, great story, all the things, everything works out. They weren't manipulating numbers. Is 6.8% enough for you? That's the question. Now, if you're serious about becoming a better investor, it comes down to two skills. Knowing how to value a business and having the emotional capacity to be able to handle the ups and downs in the market. Prices are always going to jump around. That's just what the market does. But value is steady and once you know how to calculate it, the noise will shake you much less. So in this next video, I'm going to show you exactly how I value a company step by step. You're going to learn what to look for, what to avoid, and how to protect yourself from overpaying for hype. The link is right here on your screen, so click it. I will

---

### id=614482 ticker=`NVDA` stored_ts=1229
`spid`: `yt_v21iatp0oC8_NVDA`

**source_verbatim_quote (narrow):**
> I'm pretty bearish on the sector. Oracle's still stuck trying to get across 200. Cororeweave can't keep it up. Enbis can't keep it up. I can't keep it up.

**±60s window (wide):**
> really, what you want to get is is a like a resumption of growth. If we can resume growth, it'd be very bullish. If we can actually get back to labor growth, uh that would be fantastic because that would just put a nail in the recession coffin. It would be very bullish. So, people are talking about their predictions for next year, which is all typically fugazy anyway. It's usually wrong by April. AI open AI faces a make or break year in 26. I agree with that. I think that's a good point from uh the economist. The that's interesting. Uh the economist or or OpenAI I should say, you know, I think if if OpenAI falters, you know, your chip sector goes gets even worse. How how are we doing today on chips? as I'm pretty bearish on the sector. Oracle's still stuck trying to get across 200. Cororeweave can't keep it up. Enbis can't keep it up. I can't keep it up. Yeah. Yeah. and and those will weigh those will keep growth in the cues slower but I still maintain uh some bullishness between now and JN 9 open eye to facemaker or break. Okay, so what do we have here? Sam Alman is like a juggler on a unicycle building all knowing snowball knowing chat bots throwing more balls into the air custom chips of course e-commerce why not business consulting too easy consumer advice you betcha at the same time Mr. Alman must keep a free hand to hold out his cap for a show gets more expensive by the day. Yeah. Yeah. This is very

---

### id=605905 ticker=`NVDA` stored_ts=544
`spid`: `yt_C5a-pfxs-zE_NVDA`

**source_verbatim_quote (narrow):**
> that Trend now reversing for 2023 if it holds what was a big headwind last year could turn into a major Tailwind four stocks in 2023

**±60s window (wide):**
> and so the value of the dollar versus foreign currency is easing up so this headwind at the very least is going away and as other central banks around the world kind of play catch up to the FED hike their interest rates as well to try to fight inflation uh the dollar could actually start to lose even more value by the second half of 2023 if the dollar starts losing value from where it was the year prior this could actually become a Tailwind for a company reporting sales outside of the United States just to recap in 2022 because of the Federal Reserve aggressively hiking interest rates the dollar the U.S dollar gained in value against foreign currencies which lowered the value of Revenue and profits for companies doing business outside of the US that Trend now reversing for 2023 if it holds what was a big headwind last year could turn into a major Tailwind four stocks in 2023 especially tech stocks including semiconductor businesses that derive a ton of business in foreign currencies outside of the US dollar hope you found this video helpful to your research make sure you hit the Subscribe button we've got more topics coming your way as we head into earnings season again fourth quarter 2022 earnings season starting this week stay tuned we're going to have a lot more videos for you as we keep you up to date on things like the dollar and giving back some value and financial reports for a lot of great companies that we cover here foreign

---

### id=614865 ticker=`NVDA` stored_ts=3324
`spid`: `yt_WbJuQYxHvco_NVDA`

**source_verbatim_quote (narrow):**
> Michael Bur will be right in the future, but I don't think Michael Bur is why markets actually sold off today. The Bur depreciation trade has everything to do with an issue that comes after the bubble bursts. In the future, the value of the chips will tank when supply catches up.

**±60s window (wide):**
> not an issue now. it will be an issue in the future. It doesn't make sense that chips that are 6 to 8 years old are still running at 100% utilization. The only reason it makes sense is because we have a supply shortage. It's just like why the hell does it make sense that Kevin got to fly around in a $13 million jet for three years and then sold the plane for a profit? Why does that make any sense? The only reason it makes sense is obviously because I'm a genius investor. No, it has to do with the fact that there's a supply shortage of those aircraft. It's the same with the chips. There's a supply shortage. So, the value stays artificially high or even in a weird way case goes up like the plane. It goes up. What? This is crazy. It's a depreciating asset. It should be going down. No. In the future, the value of those planes will tank when supply catches up. In the future, the value of the chips will tank when supply catches up. Has anything changed with depreciation curves today? No. No. No. No. >> This has nothing to do with the bur depreciation trade. The bur depreciation trade has everything to do with an issue that comes after the bubble bursts. It has to do with after growth tops off. That's when the bur depreciation trade is a problem. Now, that's actually scary. I wrote that here. That's actually scary because it means the bur depreciation trade is still ahead of us. He's too early right now, but it means it's still coming. So if the stock market falls off a cliff now, you still get to look forward to the bur depreciation trade, which is all of a sudden where the, you know, the mag sevens go, "Oh crap, we actually got to say uh that our um depreciation schedule is 2 years or 3 years instead of the six

---

### id=609132 ticker=`TSLA` stored_ts=678
`spid`: `yt_Cia9JmcvD1I_TSLA`

**source_verbatim_quote (narrow):**
> I'm starting to get very bullish on the big stocks stocks like like Visa I like Amazon I like meta I like a lot of the big seven because people are starting to hate on them and they're getting better valued and this is what I look for I look for things people hate when they love them I sell them and I move on that's what I do and I'm starting to open small positions in some of the big stocks and some of the Magnificent Seven stocks because this is what I believe will happen I told you I think it's nearing the end and we're going to go into 2025 and we might even make a new high

**±60s window (wide):**
> how or this is not when the stock market will crash and if we do have a 5% bounce on NASDAQ in the next two weeks trust me you're going to see see all kind of videos of why we're going to 7,000 because most people they follow price action they don't actually follow their own Intuition or what they believe will happen but what I believe will happen is I told you what it is I think going I go into 2025 rally all together and then this is when the crash will happen most likely in 2025 now this is what I'm doing in my portfolio I had stocks that I talked about on YouTube like nooc it's up 10 and a half% on the week it saved my ass this week you know Pepsi is up 2% McDonald's doing well I own all low stocks I also own stocks haven't been doing well like I talked about Ulta beauty got killed but it's only a small percentage of my portfolio it's not my entire one most of it is me putting my money where my mouse is in the rotation before most people even talked about it and that's what I did and these stocks are up a lot and I'm starting to get very bullish on the big stocks stocks like like Visa I like Amazon I like meta I like a lot of the big seven because people are starting to hate on them and they're getting better valued and this is what I look for I look for things people hate when they love them I sell them and I move on that's what I do and I'm starting to open small positions in some of the big stocks and some of the Magnificent Seven stocks because this is what I believe will happen I told you I think it's nearing the end and we're going to go into 2025 and we might even make a new high I wouldn't be surprised at all because most people aren't actually expecting it and this is what tends to happen in the market so I'm selling some of those stocks that I'm up on some of the Pepsi trimming some other stocks and I'm starting to buy the stocks that have been going down magnificent 7 you know and and other kind of stocks that I like in terms of Mega cap stocks and many others I don't believe the small caps are going to go down I think the small cap R is only getting started but the large caps are soon going to follow the small caps in

---

### id=606784 ticker=`TSLA` stored_ts=625
`spid`: `yt_Pdy4ITSZXqM_TSLA`

**source_verbatim_quote (narrow):**
> I'm still holding on to my shares long term and I'm still um comforted really by the more reasonable PEG ratio of just 1.3 meaning that they'll likely have a lot more profit growth in the future

**±60s window (wide):**
> size of the truck as it'll be the only sub 19-foot truck on the market that still has four doors over a six foot bed and can still fit inside of a 20-foot garage basically The Sweet Spot in terms of perfect overall size and when speaking about demand musk also said that demand is so off the hook for the Cyber truck that you can't even see the hook with building of the truck having already started and mass production likely ramping up next year however there was also a few comments that hinted towards only a limited release this year which I think the market took as a bad sign given how many times the truck has already been delayed but probably the biggest reason of all for the drop in the stock price had to do with how high it was already trading as it is still up over a hundred percent year to dates with a rich forward PE and PS ratio of almost 69 and 8 respectively so there was probably some profit taking given the recent climb I'm still holding on to my shares long term and I'm still um comforted really by the more reasonable PEG ratio of just 1.3 meaning that they'll likely have a lot more profit growth in the future but given that it's already one of my biggest Holdings I don't plan on buying any more shares at this time or anytime soon now Wednesday did have several other popular stocks reporting as well uh like Goldman Sachs and IBM but the ones that I'll just quickly touch on here were U.S Bancorp and United Airlines now U.S Bancorp is actually one of my newer pickups in my own portfolio and it's currently ranked uh the fifth largest bank in America and carries a really attractive dividend of around five percent with with some solid growth metrics on it too the stock actually Rose this week by close to 10 percent despite what looked to be a pretty bad earnings report at first glance as they only slightly beat estimates but saw net income interest drop by around four percent with also lower guidance than

---

### id=612006 ticker=`NVDA` stored_ts=2299
`spid`: `yt_lCutvv3YIKM_NVDA`

**source_verbatim_quote (narrow):**
> So, my prediction is that some of these stocks will do quite well. Um will they or won't they? I'm not sure. But uh these are the ones which uh screen pretty well. And you can see I've got two from each industry.

**±60s window (wide):**
> looks at just two things. It looks at price momentum and it looks at earnings momentum. So if both of those are also po pointing in a positive direction, what's good about adding this means that you don't have to wait around for too long. But these are the companies which which which score highly. So don't forget the loes UK small caps. So I've got quality rank, value rank, momentum rank, all over 50. And then the market cap has got to be small but not tiny. So greater than 100 million but less than a billion. And it's not going to be too illquid. So if the bid offer spreads more than five percentage points, well, I'm not going to buy it because, you know, it's so expensive to trade. So that's another hurdle to making a profit. Um, but anyway, these are the companies which screen well based on that criterion. And then the ones I've currently got are here. based on when I did my uh last screen. So my prediction is that some of these stocks will do quite well. Um will they or won't they? I'm not sure. But uh these are the ones which uh screen pretty well. And you can see I've got two from each industry. So I've got two from industrials, two from financials and so on. Um some sectors are just too small. So I can't find the stocks for it. But uh because I've filtered down based on so many criteria but these are the ones which I currently hold. So yeah my prediction if you want one is that those will do well. I've also got a copper portfolio which um which is copper miners and that's actually doing well now. You know I've beaten the UK small cap index because of the gold miners. Um but yeah that's that's another one which I do based on fundamentals. So I get their uh stock rank out of Stockipedia and I choose the ones which have got the best fundamentals but which also get a fair chunk of their revenue from copper. It's

---

### id=606541 ticker=`GOOGL` stored_ts=632
`spid`: `yt_EylJpfJY_vs_GOOGL`

**source_verbatim_quote (narrow):**
> Investors realizing that future profits are going to be much smaller than expected suddenly makes today's stock prices look egregiously high, and the fall back to earth could be violent.

**±60s window (wide):**
> depreciation again from 5 to 6 years and boosted profits by another 1.2 billion yuan. Well, fast-forward to their latest quarterly results from this week, and the company was forced to report a 16 billion yuan impairment expense. The management team stated, "Some of the existing assets no longer meet today's computing efficiency requirements." And that might just be the understatement of the century. The green bars on this chart are Baidu's pre-tax profits for the past 18 months. The orange bar is the impairment. So, before the impairment, total profits were 40.7 billion yuan. In reality, it was more like 25 billion yuan. And no, this isn't because it's a Chinese company. They did the same accounting tricks as the American tech giants. The only difference is Baidu is tiny compared to them. So, if the same thing happens in the US, it could be ugly. Investors realizing that future profits are going to be much smaller than expected suddenly makes today's stock prices look egregiously high, and the fall back to earth could be violent. Also, I've seen some people push back and say it doesn't matter because all of this is visible in the cash flow statements. Burry's implication that they are cooking the books or hiding accounting is completely false because all of the accounting is apparent in the cash flow statement. It's all there. They're following GAAP standards, and then investors make a market. And they all decide, what do I want to value this company on? Cash flow? EBITDA? Yes, Burry is using the term fraud pretty liberally here. The spending is fully reported on the cash flow statements. But the point is that companies are telling investors that the 90 billion dollars for servers, for example, is a lump sum payment that will provide benefits for many years. If that narrative changes to, well, actually, we just need to spend 90 billion dollars every single year to survive,

---

## Bucket D detail (no transcript)

- id=607674 ticker=`AAPL` ts=401 status=`error: ChunkedEncodingError: ('Connection broken: IncompleteRead(4128 bytes read, 6112 more expected)', IncompleteRead(4128 bytes read, 6112 more exp` spid=`yt_NjhoJ_RYAU4_AAPL`
