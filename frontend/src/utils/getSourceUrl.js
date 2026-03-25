/**
 * Generate the best possible source link for a prediction.
 * Uses a specific post URL if available, otherwise generates a contextual search link.
 */
export default function getSourceUrl(prediction, forecaster) {
  const ticker = prediction.ticker;
  const platform = forecaster?.platform || prediction.source_type;
  const handle = forecaster?.handle || '';
  const channelUrl = forecaster?.channel_url || prediction.source_url || '';

  // If we have a real specific post URL — use it directly
  if (prediction.source_url && (
    prediction.source_url.includes('/status/') ||
    prediction.source_url.includes('/watch?v=') ||
    prediction.source_url.includes('/comments/')
  )) {
    return { url: prediction.source_url, type: 'direct' };
  }

  // YouTube: search their channel for the ticker
  if (platform === 'youtube' || channelUrl.includes('youtube.com')) {
    const channelHandle = channelUrl.split('@')[1]?.split('/')[0] || '';
    if (channelHandle) {
      return {
        url: `https://www.youtube.com/@${channelHandle}/search?query=${ticker}`,
        type: 'search',
        label: `Search ${ticker} on their channel`,
        tooltip: `Search @${channelHandle}'s YouTube channel for ${ticker} mentions`,
        icon: 'youtube',
      };
    }
    return {
      url: `https://www.youtube.com/results?search_query=${ticker}+${handle.replace('@', '')}`,
      type: 'search',
      label: `Search ${ticker} on YouTube`,
      tooltip: `Search YouTube for ${ticker} by ${handle}`,
      icon: 'youtube',
    };
  }

  // X/Twitter, Congress, Institutional (if X-based)
  if (platform === 'x' || platform === 'twitter' || platform === 'congress' ||
      (platform === 'institutional' && channelUrl.includes('x.com'))) {
    const xHandle = handle.replace('@', '') || channelUrl.split('x.com/')[1]?.split('/')[0];
    if (xHandle) {
      return {
        url: `https://x.com/search?q=from%3A${xHandle}+%24${ticker}&f=live`,
        type: 'search',
        label: `Search $${ticker} tweets`,
        tooltip: `Search @${xHandle}'s tweets mentioning $${ticker}`,
        icon: 'twitter',
      };
    }
    return {
      url: `https://x.com/search?q=%24${ticker}&f=live`,
      type: 'search',
      label: `Search $${ticker} on X`,
      tooltip: `Search X for $${ticker}`,
      icon: 'twitter',
    };
  }

  // Reddit
  if (platform === 'reddit' || channelUrl.includes('reddit.com')) {
    const subreddit = channelUrl.includes('/r/')
      ? channelUrl.split('/r/')[1]?.split('/')[0]
      : null;
    if (subreddit) {
      return {
        url: `https://www.reddit.com/r/${subreddit}/search/?q=${ticker}&restrict_sr=1&sort=new`,
        type: 'search',
        label: `Search ${ticker} posts`,
        tooltip: `Search r/${subreddit} for ${ticker} posts`,
        icon: 'reddit',
      };
    }
    const username = channelUrl.split('/user/')[1]?.split('/')[0];
    if (username) {
      return {
        url: `https://www.reddit.com/user/${username}/submitted/?q=${ticker}`,
        type: 'search',
        label: `Search ${ticker} posts`,
        tooltip: `Search u/${username}'s posts for ${ticker}`,
        icon: 'reddit',
      };
    }
    return {
      url: `https://www.reddit.com/search/?q=${ticker}&sort=new`,
      type: 'search',
      label: `Search ${ticker} on Reddit`,
      tooltip: `Search Reddit for ${ticker}`,
      icon: 'reddit',
    };
  }

  // Fallback
  if (channelUrl) {
    return { url: channelUrl, type: 'profile' };
  }

  return null;
}
